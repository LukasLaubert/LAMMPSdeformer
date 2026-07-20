#!/usr/bin/env python3
"""
LAMMPSdeformer Script Generator

Handles the generation of LAMMPS input scripts and cluster job files
based on user configuration with support for symmetric wall movement,
engineering strain (tensile and shear), proper units handling, 
and structured file generation.

This version implements a robust Phase Setup / Caller architecture 
to ensure mathematical continuity for thermostats/barostats across
HPC predictive walltime chunking and restarts.
"""

import os
import json
import glob
import subprocess
import tempfile
import math
import shutil
from pathlib import Path
from datetime import datetime

class LAMMPSdeformerGenerator:
    """Generates LAMMPS input scripts and job files"""
    
    def __init__(self, config):
        """Initialize with configuration dictionary"""
        self.config = config
        self.generated_files = []
        
    def validate_configuration(self):
        """
        Performs strict read-only validation of paths and settings.
        Returns a dictionary containing success status, messages, derived data, and warnings.
        """
        warnings = []
        
        # 1. Validate General Config
        if not isinstance(self.config, dict):
            return {"success": False, "message": "Invalid configuration: not a dictionary"}
        
        system_config = self.config.get("system", {})
        if not isinstance(system_config, dict):
            return {"success": False, "message": "Invalid system configuration"}
            
        # 2. Validate System Sets
        system_sets = system_config.get("system_sets", [])
        if not system_sets:
            # Fallback to legacy single path if system_sets is missing
            system_path = system_config.get("system_path", "")
            if not system_path:
                return {"success": False, "message": "No data sets defined."}
            system_sets = [{
                "system_path": system_path,
                "data_file_extensions": system_config.get("data_file_extensions", [".data"]),
                # Before Potential
                "use_potential_before": system_config.get("use_potential_before", False),
                "potential_file_before": system_config.get("potential_file_before", ""),
                "potential_source_before": system_config.get("potential_source_before", "file"),
                "potential_content_before": system_config.get("potential_content_before", ""),
                # After Potential
                "use_potential_after": system_config.get("use_potential_after", False),
                "potential_file_after": system_config.get("potential_file_after", ""),
                "potential_source_after": system_config.get("potential_source_after", "file"),
                "potential_content_after": system_config.get("potential_content_after", ""),
                "is_enabled": True
            }]

        validated_sets = []
        for i, s_set in enumerate(system_sets):
            if not s_set.get("is_enabled", True):
                continue

            path = s_set.get("system_path", "")
            if not path:
                return {"success": False, "message": f"System path not specified for Data Set {i+1}"}
            
            if not os.path.exists(path):
                return {"success": False, "message": f"Path does not exist for Data Set {i+1}: {path}"}

            if os.path.isfile(path):
                set_files = [path]
            elif os.path.isdir(path):
                exts = s_set.get("data_file_extensions", [".data"])
                set_files = []
                for ext in exts:
                    set_files.extend(glob.glob(os.path.join(path, f"*{ext}")))
                if not set_files:
                    return {"success": False, "message": f"No data files found in {path} for Data Set {i+1}"}
            else:
                return {"success": False, "message": f"Invalid path type for Data Set {i+1}: {path}"}
            
            # Validate Before/After Potential Settings
            for suffix, label in [("_before", "before"), ("_after", "after")]:
                if s_set.get(f"use_potential{suffix}", False):
                    source = s_set.get(f"potential_source{suffix}", "file")
                    if source == "file":
                        p_file = s_set.get(f"potential_file{suffix}", "")
                        if not p_file or not os.path.exists(p_file):
                            return {"success": False, "message": f"Potential file ({label}) missing or invalid for Data Set {i+1}"}
                    elif source == "text":
                        if not s_set.get(f"potential_content{suffix}", "").strip():
                            return {"success": False, "message": f"Potential commands ({label}) missing for Data Set {i+1}"}

            if len(system_sets) > 1 and "name" in s_set:
                base_name = s_set["name"]
            else:
                base_name = Path(path).stem

            validated_sets.append({
                "config": s_set,
                "files": set_files,
                "name": base_name
            })

        if not validated_sets:
            return {"success": False, "message": "No active data sets selected."}

        # 3. Check Units Consistency
        all_active_files = []
        for v_set in validated_sets:
            all_active_files.extend(v_set["files"])
            
        if len(all_active_files) > 1:
            units_check = self.check_units_consistency(all_active_files)
            if not units_check["consistent"]:
                warnings.append(f"WARNING: {units_check['message']}")
        
        # 4. Validate Deformation Studies
        deform_studies = self.config.get("multistudy", {}).get("deform_studies", [])
        if not deform_studies:
            return {"success": False, "message": "No deformation studies defined."}
        
        for i, study in enumerate(deform_studies):
            if not isinstance(study, dict):
                return {"success": False, "message": f"Invalid deformation study at index {i}"}
            
            required_fields = ["name", "data_points", "max_steps", "min_strain", "max_strain"]
            for field in required_fields:
                if field not in study:
                    return {"success": False, "message": f"Missing field '{field}' in deformation study '{study.get('name', f'study_{i}')}'"}
        
        output_config = self.config.get("output", {})
        if not isinstance(output_config, dict):
            return {"success": False, "message": "Invalid output configuration"}
            
        return {
            "success": True, 
            "message": "Validation successful", 
            "warnings": warnings, 
            "validated_sets": validated_sets
        }

    def generate_all_scripts(self):
        """Generate all necessary scripts based on configuration"""
        try:
            self.generated_files = []
            
            val_result = self.validate_configuration()
            if not val_result["success"]:
                return val_result
            
            warnings = val_result["warnings"]
            validated_sets = val_result["validated_sets"]
            
            system_config = self.config.get("system", {})
            output_config = self.config.get("output", {})
            deform_studies = self.config.get("multistudy", {}).get("deform_studies", [])

            total_sets_in_ui = len(system_config.get("system_sets", []))
            use_naming_prefix = total_sets_in_ui > 1
            
            output_path = output_config.get("output_path", "")
            if not output_path:
                output_path = os.path.dirname(validated_sets[0]["files"][0])
            
            root_simulation_dir = output_path
            os.makedirs(root_simulation_dir, exist_ok=True)
            
            data_files_folder = os.path.join(root_simulation_dir, "_input_files")
            os.makedirs(data_files_folder, exist_ok=True)
            
            base_settings_result = self.generate_base_settings_file(root_simulation_dir)
            if not base_settings_result["success"]:
                return base_settings_result
            
            all_simulations = [] 
            
            # Tracking for synced potentials
            synced_refs = {"before": None, "after": None}
            synced_processed = {"before": False, "after": False}

            for set_idx, v_set in enumerate(validated_sets):
                set_config = v_set["config"]
                set_files = v_set["files"]
                set_base_name = v_set["name"]
                prefix = f"{set_base_name}_" if use_naming_prefix else ""
                
                potential_refs = {"before": None, "after": None}
                
                for suffix in ["before", "after"]:
                    if set_config.get(f"use_potential_{suffix}", False):
                        source = set_config.get(f"potential_source_{suffix}", "file")
                        if set_config.get(f"sync_potential_{suffix}", False):
                            if not synced_processed[suffix]:
                                if source == "file":
                                    potential_file = set_config.get(f"potential_file_{suffix}", "")
                                    if potential_file and os.path.exists(potential_file):
                                        unique_pot_name = f"{suffix}_synced_{Path(potential_file).name}"
                                        potential_dest = os.path.join(data_files_folder, unique_pot_name)
                                        shutil.copy2(potential_file, potential_dest)
                                        synced_refs[suffix] = f"_input_files/{unique_pot_name}"
                                elif source == "text":
                                    potential_content = set_config.get(f"potential_content_{suffix}", "")
                                    unique_pot_name = f"{suffix}_synced_custom.potential"
                                    potential_dest = os.path.join(data_files_folder, unique_pot_name)
                                    with open(potential_dest, 'w') as f:
                                        f.write(potential_content)
                                    synced_refs[suffix] = f"_input_files/{unique_pot_name}"
                                synced_processed[suffix] = True
                            potential_refs[suffix] = synced_refs[suffix]
                        else:
                            if source == "file":
                                potential_file = set_config.get(f"potential_file_{suffix}", "")
                                if potential_file and os.path.exists(potential_file):
                                    pot_name = Path(potential_file).name
                                    unique_pot_name = f"{suffix}_{prefix}{pot_name}"
                                    potential_dest = os.path.join(data_files_folder, unique_pot_name)
                                    shutil.copy2(potential_file, potential_dest)
                                    potential_refs[suffix] = f"_input_files/{unique_pot_name}"
                            elif source == "text":
                                potential_content = set_config.get(f"potential_content_{suffix}", "")
                                pot_name = "custom.potential"
                                unique_pot_name = f"{suffix}_{prefix}{pot_name}"
                                potential_dest = os.path.join(data_files_folder, unique_pot_name)
                                with open(potential_dest, 'w') as f:
                                    f.write(potential_content)
                                potential_refs[suffix] = f"_input_files/{unique_pot_name}"

                for study in deform_studies:
                    study_name = study.get("name", "study")
                    study_folder_name = study_name if prefix and study_name.startswith(prefix) else f"{prefix}{study_name}"
                    study_folder = os.path.join(root_simulation_dir, study_folder_name)
                    os.makedirs(study_folder, exist_ok=True)

                    for system_file in set_files:
                        system_name = Path(system_file).stem
                        unique_data_name = f"{system_name}.data" if prefix and system_name.startswith(prefix) else f"{prefix}{system_name}.data"
                        data_file_dest = os.path.join(data_files_folder, unique_data_name)
                        shutil.copy2(system_file, data_file_dest)
                        data_file_relative_path = f"_input_files/{unique_data_name}"

                        sim_folder = os.path.join(study_folder, system_name)
                        os.makedirs(sim_folder, exist_ok=True)
                        
                        # Avoid double naming if system_name already starts with the prefix
                        if prefix and system_name.startswith(prefix):
                            # Use study_name and strip prefix if it's there too
                            study_part = study_name
                            if study_part.startswith(prefix):
                                study_part = study_part[len(prefix):]
                            model_name = f"{study_part}_{system_name}"
                        else:
                            model_name = f"{study_folder_name}_{system_name}"

                        # Final guard for exact redundancy (e.g. system name already includes study)
                        if system_name.startswith(f"{study_folder_name}_"):
                            model_name = system_name
                        
                        result = self.generate_single_script(
                            system_file, model_name, study, 
                            sim_folder, data_file_relative_path,
                            potential_before_ref=potential_refs["before"],
                            potential_after_ref=potential_refs["after"],
                            set_config=set_config
                        )
                        
                        if not result["success"]:
                            return result
                            
                        all_simulations.append({
                            "study_folder": study_folder_name,
                            "system_folder": system_name,
                            "model_name": model_name
                        })
            
            exec_script_result = self.generate_execution_script(root_simulation_dir, all_simulations)
            if not exec_script_result["success"]:
                return exec_script_result
            
            cluster_script_result = self.generate_cluster_submission_script(root_simulation_dir, all_simulations)
            if not cluster_script_result["success"]:
                return cluster_script_result
            
            settings_result = self.save_settings_to_json(root_simulation_dir)
            if not settings_result["success"]:
                return settings_result
            
            final_msg = f"Successfully generated {len(self.generated_files)} scripts across {len(validated_sets)} data sets."
            if warnings:
                final_msg += "\n\n" + "\n".join(warnings)

            return {"success": True, "message": final_msg, "files": self.generated_files}
            
        except Exception as e:
            return {"success": False, "message": f"Error generating scripts: {str(e)}"}

    def save_settings_to_json(self, root_simulation_dir):
        """Save all settings to a JSON file in the root folder"""
        try:
            settings_file = os.path.join(root_simulation_dir, "lammps_settings.json")
            with open(settings_file, 'w') as f:
                json.dump(self.config, f, indent=2)
            self.generated_files.append(settings_file)
            return {"success": True, "message": f"Settings saved to: {settings_file}"}
        except Exception as e:
            return {"success": False, "message": f"Error saving settings: {str(e)}"}
        
    def check_units_consistency(self, system_files):
        """Check if all data files have the same units, ignoring unknown ones."""
        if not system_files:
            return {"consistent": True, "units": None, "message": ""}
            
        defined_units = set()
        first_file_with_units = None
        
        for file_path in system_files:
            units = self.read_units_from_data_file(file_path)
            if units:
                defined_units.add(units)
                if not first_file_with_units:
                    first_file_with_units = (file_path, units)
                    
        if len(defined_units) <= 1:
            return {"consistent": True, "units": list(defined_units)[0] if defined_units else None}
            
        return {
            "consistent": False, 
            "message": f"Units mismatch detected in source files: {defined_units}. The generator will proceed using the units defined in the System Configuration tab ('{self.config.get('system', {}).get('units', 'unknown')}'). Please check your input data files before running the simulations!"
        }
        
    def generate_single_script(self, data_file, model_name, deform_study, output_dir, data_file_dest, potential_before_ref=None, potential_after_ref=None, set_config=None):
        """Generate a single LAMMPS input script"""
        try:
            script_filename = os.path.join(output_dir, f"{model_name}.in")
            script_content = self.generate_script_content(data_file_dest, model_name, deform_study, potential_before_ref, potential_after_ref, set_config)
            with open(script_filename, 'w') as f:
                f.write(script_content)
            self.generated_files.append(script_filename)
            return {"success": True, "message": f"Script generated: {script_filename}", "script_file": script_filename}
        except Exception as e:
            return {"success": False, "message": f"Error generating script: {str(e)}"}

    def generate_script_content(self, data_file, model_name, deform_study, potential_before_ref=None, potential_after_ref=None, set_config=None):
        """Generate the content of a LAMMPS input script using the Call-Setup architecture"""
        try:
            system_config = self.config.get("system", {})
            if set_config is None:
                set_config = system_config
                
            fixes_config = self.config.get("fixes", {})
            output_config = self.config.get("output", {}).copy()
            job_submission_config = self.config.get("job_submission", {})
            enable_restart = job_submission_config.get("enable_restart", False)
            restart_freq = job_submission_config.get("restart_freq", 100000) if enable_restart else float('inf')
            max_steps = deform_study.get("max_steps", 0)

            script_lines = [
                f"# {model_name}.in",
                f"# Generated by LAMMPSdeformer on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", "",
                "#------------------------", "# Base settings", "#------------------------", "include ../../base_input.in", ""
            ]

            # 1. Potential BEFORE data
            if potential_before_ref:
                script_lines.extend(["# Potential BEFORE data setup", f"include ../../{potential_before_ref}", ""])

            if enable_restart:
                script_lines.extend([
                    "#------------------------", "# Restart Setup", "#------------------------",
                    "shell \"mkdir -p restart_files\"",
                    "if \"${curstep} > 0\" then \"read_restart restart_files/" + str(model_name) + ".restart.${curstep}\" &",
                    "else &",
                    f"  \"read_data ../../{data_file}\"",
                    ""
                ])
            else:
                script_lines.extend(["#------------------------", "# System Setup", "#------------------------"])
                script_lines.append(f"read_data ../../{data_file}")
                script_lines.append("")
            
            # --- Triclinic Box Check (Directly after read_data) ---
            deform_axis = deform_study.get("deform_axis", "x")
            mode = deform_study.get("mode", "Deformation")
            is_shear = deform_axis in ["xy", "xz", "yz"]
            ensemble_config = deform_study.get("ensemble", {})
            
            # Check if we need to convert to triclinic
            if (ensemble_config.get("ensemble") == "NPT" and ensemble_config.get("npt_aniso") == "tri") or is_shear:
                if enable_restart:
                     # Only change box if we are starting fresh (step 0), otherwise restart file has it.
                     script_lines.extend(["if \"${curstep} == 0\" then \"change_box all triclinic\"", ""])
                else:
                     script_lines.extend(["change_box all triclinic", ""])

            # 2. Potential AFTER data (and after potential box changes)
            if potential_after_ref:
                script_lines.extend(["# Potential AFTER data/box setup", f"include ../../{potential_after_ref}", ""])
                
            if enable_restart:
                new_lines = [
                    "#------------------------",
                    "# Initial Box Dimensions Handling",
                    "#------------------------",
                    "if \"${curstep} == 0\" then &",
                    "  \"shell echo variable L0x equal $(lx) > restart.init\" &",
                    "  \"shell echo variable L0y equal $(ly) >> restart.init\" &",
                    "  \"shell echo variable L0z equal $(lz) >> restart.init\" &",
                    "  \"shell echo variable xlo0 equal $(xlo) >> restart.init\" &",
                    "  \"shell echo variable xhi0 equal $(xhi) >> restart.init\" &",
                    "  \"shell echo variable ylo0 equal $(ylo) >> restart.init\" &",
                    "  \"shell echo variable yhi0 equal $(yhi) >> restart.init\" &",
                    "  \"shell echo variable zlo0 equal $(zlo) >> restart.init\" &",
                    "  \"shell echo variable zhi0 equal $(zhi) >> restart.init\" &",
                    "else \"shell if [ ! -f restart.init ]; then echo 'ERROR: Restarting, but restart.init not found. Initial dimensions are unknown.' && exit 1; fi\"",
                    "include restart.init",
                    ""
                ]
            else:
                new_lines = [
                    "variable L0x equal $(lx)",
                    "variable L0y equal $(ly)",
                    "variable L0z equal $(lz)",
                    "variable xlo0 equal $(xlo)",
                    "variable xhi0 equal $(xhi)",
                    "variable ylo0 equal $(ylo)",
                    "variable yhi0 equal $(yhi)",
                    "variable zlo0 equal $(zlo)",
                    "variable zhi0 equal $(zhi)",
                    ""
                ]

            script_lines.extend(new_lines)

            pressure = self._format_float(ensemble_config.get("pressure", 1.0))
            script_lines.extend([f"variable base_pressure equal {pressure}", ""])

            if mode == "Temperature":
                script_lines.extend(["#------------------------", "# Temperature Variables", "#------------------------"])
                points = deform_study.get("data_points", [])
                initial_temp = points[0][1] if points else 300.0
                script_lines.extend([f"variable set_temp equal {initial_temp}", ""])

            if system_config.get("enable_velocity", True):
                points = deform_study.get("data_points", [])
                initial_temp = points[0][1] if mode == "Temperature" and points else ensemble_config.get("temperature", 300.0)
                velocity_command = f"velocity all create {initial_temp} {system_config.get('initial_velocity_seed', 12345)} mom yes rot yes dist gaussian"
                
                if enable_restart:
                    script_lines.extend([
                        "#------------------------", "# Initial Velocity", "#------------------------",
                        "if \"${curstep} == 0\" then \"" + str(velocity_command) + "\"",
                        ""
                    ])
                else:
                    script_lines.extend([
                        "#------------------------", "# Initial Velocity", "#------------------------",
                        velocity_command,
                        ""
                    ])

            fixes_computes_lines, final_thermo_style = self._generate_fixes_computes_section(deform_study, output_config, fixes_config, mode, deform_axis, is_shear)
            if fixes_computes_lines:
                script_lines.extend(["#------------------------", "# Fixes & Computes", "#------------------------", *fixes_computes_lines])
            
            bond_commands_config = deform_study.get("bond_commands", {})
            bond_commands_text = bond_commands_config.get("commands", "").strip()

            if bond_commands_text: 
                script_lines.extend(["#------------------------", "# Study-specific Commands", "#------------------------"])
                for line in bond_commands_text.split('\n'):
                    line = line.strip()
                    if line and not line.startswith('#'): 
                        script_lines.append(line)
                script_lines.append("") 

            bond_breakage_config = deform_study.get("bond_breakage", {})
            if bond_breakage_config.get("enable_bond_breakage", False):
                script_lines.extend(self._generate_bond_breakage_section(bond_breakage_config))
            
            output_lines = self._generate_output_section(output_config, model_name, final_thermo_style)
            if output_lines:
                 script_lines.extend(["#------------------------", "# Output Settings", "#------------------------", *output_lines])
            
            # ==========================================================
            # MAIN SIMULATION LOGIC (New Caller Architecture)
            # ==========================================================
            script_lines.extend([
                "#===========================================================", 
                "# Main Simulation Logic", 
                "#===========================================================", 
                ""
            ])
            
            write_data_option = output_config.get("write_data_option", "At the end of the simulation")
            base_name = Path(data_file).stem
            write_data_filename = f"{base_name}_*.data"

            # Global phase tracker
            script_lines.extend([
                "variable active_phase equal 0",
                ""
            ])

            if enable_restart:
                script_lines.extend([
                    "# --- Timer and Maximum Time Setup for Predictive Quit ---",
                    "variable global_start_time timer",
                    "variable chunk_start_time timer",
                    "variable max_chunk_time equal 0.0",
                    ""
                ])

            execution_blocks = self._generate_execution_blocks(deform_study, enable_restart, restart_freq)
            user_handle_steps = {int(p[0]) for p in deform_study.get("data_points", []) if int(p[0]) > 0}

            # 1. Distribution Hub
            script_lines.extend(["# --- Jump to correct segment based on current step ---", "label segment_distribution"])
            
            if execution_blocks:
                first_step = execution_blocks[0]['start_step']
                script_lines.append(f"if \"${{curstep}} == {first_step}\" then \"jump SELF segment_{execution_blocks[0]['user_segment_id']}_{first_step}\"")
                
            if enable_restart:
                restart_steps = sorted(list(set([block['start_step'] for block in execution_blocks if block['start_step'] > 0])))
                for step in restart_steps:
                    block = next((b for b in execution_blocks if b['start_step'] == step), None)
                    if block: 
                        script_lines.append(f"if \"${{curstep}} == {step}\" then \"jump SELF segment_{block['user_segment_id']}_{step}\"")

            if max_steps > 0:
                script_lines.append(f"if \"${{curstep}} >= {int(max_steps)}\" then \"jump SELF end\"")

            if enable_restart:
                script_lines.extend(["if \"${curstep} > 0\" then \"print 'ERROR: Restart step ${curstep} does not match any known segment start. Aborting.' ; quit\"", ""])
            else:
                script_lines.append("")

            # 2. Setup Blocks (Generated once per physical phase)
            script_lines.append("# --- Phase Setup Blocks ---")
            processed_phases = set()
            for block in execution_blocks:
                uid = block['user_segment_id']
                if uid not in processed_phases:
                    script_lines.extend(self._generate_setup_block(block, deform_study, system_config, is_shear))
                    processed_phases.add(uid)
            script_lines.extend(["", ""])

            # 3. Main Execution Chunks
            script_lines.append("# --- Main Execution Loop ---")
            for block in execution_blocks:
                if enable_restart and block['start_step'] > 0 and block['start_step'] % restart_freq == 0:
                    script_lines.extend([
                        f"\n# --- Restart Chunk Boundary at step {block['start_step']} ---",
                        "variable current_time timer",
                        "variable current_chunk_time equal $(v_current_time-v_chunk_start_time)",
                        "variable current_global_time equal $(v_current_time-v_global_start_time)",
                        "if \"${current_chunk_time} > ${max_chunk_time}\" then \"variable max_chunk_time equal ${current_chunk_time}\"",
                        f"write_restart restart_files/{model_name}.restart.*",
                        "variable predict_elapsed equal $(v_current_global_time+v_max_chunk_time)",
                        "print \"Current Time=${current_global_time}s, Max Chunk time=${max_chunk_time}s, Predicted Next=${predict_elapsed}s, Max time allowed=${maxtime}s\"",
                        "if \"${predict_elapsed} > ${maxtime}\" then &",
                        "  \"print 'PREDICTIVE QUIT: Estimated next chunk would exceed walltime.'\" &",
                        "  \"shell 'touch resubmit.flag'\" &",
                        "  \"quit\" &",
                        "else &",
                        "  \"print 'Time check: OK.'\"",
                        "variable chunk_start_time timer"
                    ])
                    
                script_lines.extend(self._generate_chunk_block(block, deform_study, model_name))
                
                if write_data_option == "After each deformation/temperature step":
                    if block['end_step'] in user_handle_steps:
                        script_lines.extend(["", f"# Write data at handle at step {block['end_step']}", f"write_data {write_data_filename}"])

            if enable_restart and max_steps > 0 and max_steps % restart_freq == 0:
                script_lines.extend([
                    "\n# --- Final Chunk Check ---",
                    "variable current_time timer",
                    "variable current_chunk_time equal $(v_current_time - v_chunk_start_time)",
                    "if \"${current_chunk_time} > ${max_chunk_time}\" then \"variable max_chunk_time equal ${current_chunk_time}\"",
                    f"write_restart restart_files/{model_name}.restart.*"
                ])

            if execution_blocks: script_lines.append(f"\njump SELF end")

            script_lines.extend(["\n# --- Simulation End ---", "label end"])
            if write_data_option == "At the end of the simulation":
                script_lines.extend([f"write_data {write_data_filename}"])
            script_lines.extend(["print \">>> Simulation complete at step $(step)\""])
            script_lines.append("shell \"touch finished.flag\"")

            return "\n".join(script_lines)

        except Exception as e:
            import traceback
            traceback.print_exc()
            return f"# Error generating script content: {str(e)}\n# Please check your configuration."

    def _generate_execution_blocks(self, deform_study, enable_restart, restart_freq):
        """Creates a unified list of execution blocks, maintaining global phase knowledge."""
        points = deform_study.get("data_points", []).copy()
        segments = deform_study.get("segments", [])
        max_steps = deform_study.get("max_steps", 0)

        if not points: return []
        if int(points[0][0]) != 0: points.insert(0, [0, points[0][1]])
        
        event_steps = {0, int(max_steps)}
        for p in points: event_steps.add(int(p[0]))
        
        if enable_restart:
            step = restart_freq
            while step < max_steps:
                event_steps.add(step)
                step += restart_freq
            
        sorted_steps = sorted(list(event_steps))

        blocks = []
        user_segment_idx = 0
        for i in range(len(sorted_steps) - 1):
            start_step, end_step = sorted_steps[i], sorted_steps[i+1]
            if start_step >= end_step: continue

            while (user_segment_idx + 1 < len(points) and end_step > int(points[user_segment_idx + 1][0])):
                user_segment_idx += 1
            
            segment_info = segments[user_segment_idx] if user_segment_idx < len(segments) else {'type': 'line'}

            p1 = points[user_segment_idx]
            p2 = points[user_segment_idx + 1] if user_segment_idx + 1 < len(points) else p1
            
            block_info = {
                "start_step": start_step,
                "end_step": end_step,
                "user_segment_id": user_segment_idx + 1,
                "segment_info": segment_info,
                "phase_start_step": int(p1[0]),
                "phase_end_step": int(p2[0]),
                "phase_start_y": float(p1[1]),
                "phase_end_y": float(p2[1])
            }

            blocks.append(block_info)
        return blocks

    def _generate_setup_block(self, block_info, deform_study, system_config, is_shear):
        """Generates the single-execution Setup Block for a given physical phase."""
        lines = []
        uid = block_info['user_segment_id']
        phase_start_step = block_info['phase_start_step']
        phase_end_step = block_info['phase_end_step']
        phase_start_y = block_info['phase_start_y']
        phase_end_y = block_info['phase_end_y']
        segment_info = block_info['segment_info']
        
        mode = deform_study.get("mode", "Deformation")
        deform_axis = deform_study.get("deform_axis", "x")
        ensemble_config = deform_study.get("ensemble", {})
        remap_val = deform_study.get("remap", "x")
        is_strain_recovery = segment_info.get('strain_recovery', False)

        temp_start_ens = self._format_float(phase_start_y) if mode == "Temperature" else self._format_float(ensemble_config.get("temperature", 300.0))
        temp_end_ens = self._format_float(phase_end_y) if mode == "Temperature" else self._format_float(ensemble_config.get("temperature", 300.0))
        pressure = self._format_float(ensemble_config.get("pressure", 1.0))
        damping = self._format_float(system_config.get("damping_factor", 100.0))

        lines.append(f"\n# --- Phase {uid} Setup ---")
        lines.append(f"label segment_{uid}_setup")
        lines.append(f"variable active_phase equal {uid}")

        # --- Dynamic Temperature Setup ---
        if mode == "Temperature":
            duration = phase_end_step - phase_start_step
            if duration > 0:
                slope = (phase_end_y - phase_start_y) / duration
                lines.append(f"variable ramp_slope equal {self._format_float(slope)}")
                lines.append(f"variable set_temp equal \"{self._format_float(phase_start_y)} + (step - {phase_start_step}) * v_ramp_slope\"")
            else:
                lines.append(f"variable set_temp equal {self._format_float(phase_end_y)}")

        # --- Deform Setup ---
        if mode == "Deformation" and not is_strain_recovery:
            if segment_info.get('type') == 'sine':
                amp = self._format_float(segment_info.get('amplitude_strain', 0))
                period = self._format_float(segment_info.get('period_steps', 0))
                phase = self._format_float(segment_info.get('phase_shift_steps', 0))
                ashift = self._format_float(segment_info.get('ashift_factor', 0))
                
                if deform_axis == "vol":
                    lines.append(f"variable Sp equal {period}")
                    lines.append(f"variable phaseShift equal {phase}")
                    deform_parts = []
                    for ax in ['x', 'y', 'z']:
                        lines.extend([
                            f"variable A{ax} equal {amp}*v_L0{ax}",
                            f"variable Ashift_{ax} equal {ashift}*v_A{ax}",
                            f"variable current_wave_val_{ax} equal \"v_A{ax} * sin(2*PI * (step-v_phaseShift)/v_Sp) + v_Ashift_{ax}\"",
                            f"variable wave_offset_{ax} equal ${{current_wave_val_{ax}}}",
                            f"variable displace_{ax} equal \"v_A{ax} * sin(2*PI * (step-v_phaseShift)/v_Sp) + v_Ashift_{ax} - v_wave_offset_{ax}\"",
                            f"variable rate_{ax} equal \"2*PI/v_Sp * v_A{ax} * cos(2*PI * (step-v_phaseShift)/v_Sp)\""
                        ])
                        deform_parts.append(f"{ax} variable v_displace_{ax} v_rate_{ax}")
                    lines.append(f"fix deform all deform 1 {' '.join(deform_parts)} units box remap {remap_val} flip no")
                else:
                    shear_dim_map = {'xy': 'y', 'xz': 'z', 'yz': 'z'}
                    ref_len_var = f"v_L0{shear_dim_map[deform_axis]}" if is_shear else f"v_L0{deform_axis}"
                    
                    lines.append(f"variable A equal {amp}*{ref_len_var}")
                    lines.append(f"variable Sp equal {period}")
                    lines.append(f"variable phaseShift equal {phase}")
                    lines.append(f"variable Ashift equal {ashift}*v_A")
                    
                    # Dynamic wave offset guarantees smooth resumption regardless of chunk step
                    lines.append(f"variable current_wave_val equal \"v_A * sin(2*PI * (step-v_phaseShift)/v_Sp) + v_Ashift\"")
                    lines.append(f"variable wave_offset equal ${{current_wave_val}}")
                    lines.append(f"variable displace equal \"v_A * sin(2*PI * (step-v_phaseShift)/v_Sp) + v_Ashift - v_wave_offset\"")
                    lines.append(f"variable rate equal \"2*PI/v_Sp * v_A * cos(2*PI * (step-v_phaseShift)/v_Sp)\"")
                    
                    lines.append(f"fix deform all deform 1 {deform_axis} variable v_displace v_rate units box remap {remap_val} flip no")
                
            else: 
                final_target_y = self._format_float(phase_end_y)
                if is_shear:
                    lines.append(f"variable tilt_target equal \"{final_target_y} * v_L0{deform_axis[1]}\"")
                    lines.append(f"fix deform all deform 1 {deform_axis} final ${{tilt_target}} units box remap {remap_val} flip no")
                else:
                    deform_scenario = deform_study.get("deform_scenario", "symmetric")
                    if deform_axis == "vol":
                        deform_parts = []
                        for ax in ['x', 'y', 'z']:
                            if deform_scenario == "shift hi, fix lo":
                                lines.extend([
                                    f'variable {ax}lo_target equal v_{ax}lo0',
                                    f'variable {ax}hi_target equal "v_{ax}hi0 + (v_L0{ax} * {final_target_y})"'
                                ])
                            elif deform_scenario == "shift lo, fix hi":
                                lines.extend([
                                    f'variable {ax}lo_target equal "v_{ax}lo0 - (v_L0{ax} * {final_target_y})"',
                                    f'variable {ax}hi_target equal v_{ax}hi0'
                                ])
                            else: 
                                lines.extend([
                                    f'variable {ax}lo_target equal "v_{ax}lo0 - (v_L0{ax} * {final_target_y}) / 2"',
                                    f'variable {ax}hi_target equal "v_{ax}hi0 + (v_L0{ax} * {final_target_y}) / 2"'
                                ])
                            deform_parts.append(f"{ax} final ${{{ax}lo_target}} ${{{ax}hi_target}}")
                        lines.append(f"fix deform all deform 1 {' '.join(deform_parts)} units box remap {remap_val} flip no")
                    else:
                        if deform_scenario == "shift hi, fix lo":
                            lines.extend([f'variable {deform_axis}lo_target equal v_{deform_axis}lo0', f'variable {deform_axis}hi_target equal "v_{deform_axis}hi0 + (v_L0{deform_axis} * {final_target_y})"'])
                        elif deform_scenario == "shift lo, fix hi":
                            lines.extend([f'variable {deform_axis}lo_target equal "v_{deform_axis}lo0 - (v_L0{deform_axis} * {final_target_y})"', f"variable {deform_axis}hi_target equal v_{deform_axis}hi0"])
                        else: 
                            lines.extend([f'variable {deform_axis}lo_target equal "v_{deform_axis}lo0 - (v_L0{deform_axis} * {final_target_y}) / 2"', f'variable {deform_axis}hi_target equal "v_{deform_axis}hi0 + (v_L0{deform_axis} * {final_target_y}) / 2"'])
                        lines.append(f"fix deform all deform 1 {deform_axis} final ${{{deform_axis}lo_target}} ${{{deform_axis}hi_target}} units box remap {remap_val} flip no")

        # --- Ensemble Setup ---
        study_lateral_settings = ensemble_config.get("lateral_contraction", {})
        segment_lateral_overrides = segment_info.get('lateral_overrides', {})
        effective_lateral_settings = study_lateral_settings.copy()
        for ax, override_val in segment_lateral_overrides.items():
            effective_lateral_settings[ax] = override_val

        if mode == "Deformation":
            if is_strain_recovery:
                npt_parts = []
                target_p = "0.0" if is_shear else pressure
                if deform_axis == "vol":
                    for ax in ['x', 'y', 'z']:
                        npt_parts.append(f"{ax} {target_p} {target_p} $({1000}*dt)")
                else:
                    npt_parts.append(f"{deform_axis} {target_p} {target_p} $({1000}*dt)")
                    for ax in ['x', 'y', 'z']:
                        if ax != deform_axis and effective_lateral_settings.get(ax) == "free (NPT)":
                            npt_parts.append(f"{ax} {pressure} {pressure} $({1000}*dt)")
                
                npt_aniso_effective = "tri" if is_shear else ensemble_config.get("npt_aniso", "aniso")

                if npt_aniso_effective == "tri":
                    for tilt in['xy', 'xz', 'yz']:
                        if tilt != deform_axis:
                            npt_parts.append(f"{tilt} 0.0 0.0 $({1000}*dt)")
                
                lines.append(f"fix ensemble all npt temp {temp_start_ens} {temp_end_ens} $({damping}*dt) {' '.join(npt_parts)} flip no")
            else:
                free_axes = [ax for ax, setting in effective_lateral_settings.items() if setting == "free (NPT)"]
                if not free_axes:
                    lines.append(f"fix ensemble all nvt temp {temp_start_ens} {temp_end_ens} $({damping}*dt) flip no")
                else:
                    npt_parts = []
                    for ax in free_axes:
                        npt_parts.append(f"{ax} {pressure} {pressure} $({1000}*dt)")
                    
                    npt_aniso_effective = "tri" if is_shear else ensemble_config.get("npt_aniso", "aniso")
                    if npt_aniso_effective == "tri":
                        for tilt in['xy', 'xz', 'yz']:
                            if tilt != deform_axis:
                                npt_parts.append(f"{tilt} 0.0 0.0 $({1000}*dt)")

                    lines.append(f"fix ensemble all npt temp {temp_start_ens} {temp_end_ens} $({damping}*dt) {' '.join(npt_parts)} flip no")
        elif mode == "Temperature":
            if ensemble_config.get("ensemble", "NVT") == "NVT":
                lines.append(f"fix ensemble all nvt temp {temp_start_ens} {temp_end_ens} $({damping}*dt) flip no")
            else:
                npt_aniso = ensemble_config.get("npt_aniso", "iso")
                lines.append(f"fix ensemble all npt temp {temp_start_ens} {temp_end_ens} $({damping}*dt) {npt_aniso} {pressure} {pressure} $(1000*dt) flip no")

        lines.append(f"jump SELF ${{resume_label}}")
        return lines

    def _generate_chunk_block(self, block_info, deform_study, model_name="model"):
        """Generates the execution chunk. Interpolation handled natively via start/stop."""
        lines = []
        uid = block_info['user_segment_id']
        start_step = block_info['start_step']
        end_step = block_info['end_step']
        phase_start_step = block_info['phase_start_step']
        phase_end_step = block_info['phase_end_step']
        segment_info = block_info['segment_info']
        duration = end_step - start_step
        
        mode = deform_study.get("mode", "Deformation")
        is_strain_recovery = segment_info.get('strain_recovery', False)

        lines.append(f"\n# --- Segment {uid}: from step {start_step} to {end_step} ---")
        lines.append(f"label segment_{uid}_{start_step}")

        # --- Caller Logic: Initialize Phase if needed ---
        lines.append(f"if \"${{active_phase}} != {uid}\" then &")
        lines.append(f"  \"variable resume_label string segment_{uid}_{start_step}\" &")
        lines.append(f"  \"jump SELF segment_{uid}_setup\"")

        # --- Run logic (Native Interpolation) ---
        if duration > 0:
            output_config = self.config.get("output", {})
            traj_format = output_config.get('traj_format', 'lammpstrj')
            enable_trajectory = output_config.get('enable_trajectory', True)
            traj_freq = int(output_config.get('traj_freq', 100))
            
            every_clause = ""
            if traj_format == "data" and enable_trajectory and traj_freq > 0:
                nocoeff_str = " nocoeff" if output_config.get("avoid_coefficients", True) else ""
                every_clause = f' every {traj_freq} "write_data {model_name}_*.data{nocoeff_str}"'
                
            if phase_end_step > phase_start_step:
                lines.append(f"run {int(duration)} start {phase_start_step} stop {phase_end_step}{every_clause}")
            else:
                lines.append(f"run {int(duration)}{every_clause}")

        # --- Phase Teardown ---
        if end_step == phase_end_step:
            if mode == "Deformation" and not is_strain_recovery:
                lines.append("unfix deform")
            lines.append("unfix ensemble")

        return lines

    def _generate_fixes_computes_section(self, deform_study, output_config, fixes_config, mode, deform_axis, is_shear):
        """Generates the full string for the Fixes & Computes section, including time-averaging."""
        lines = []
        base_thermo_style = output_config.get("thermo_style", "step temp press")
        thermo_style_parts = base_thermo_style.split()
        
        strain_map = {'εxx': 'strain_xx', 'εyy': 'strain_yy', 'εzz': 'strain_zz', 
                      'εxy': 'strain_xy', 'εxz': 'strain_xz', 'εyz': 'strain_yz'}
        stress_map = {'σxx': 'cauchy_xx', 'σyy': 'cauchy_yy', 'σzz': 'cauchy_zz', 
                      'σxy': 'cauchy_xy', 'σxz': 'cauchy_xz', 'σyz': 'cauchy_yz', 
                      'von Mises': 'vMises', 'hydrostatic': 'hydrostatic'}

        if mode == "Deformation":
            for strain in output_config.get("eng_strains", []):
                if strain in ['strain deformation direction', 'deformation direction']:
                    if deform_axis == "vol":
                        axis_suffix = "xx"
                    else:
                        axis_suffix = deform_axis if is_shear else deform_axis * 2
                    thermo_style_parts.append(f"v_strain_{axis_suffix}")
                elif strain in strain_map:
                    thermo_style_parts.append(f"v_{strain_map[strain]}")
            
            for stress in output_config.get("cauchy_stresses", []):
                if stress in ['stress deformation direction', 'deformation direction']:
                     if deform_axis == "vol":
                         axis_suffix = "xx"
                     else:
                         axis_suffix = deform_axis if is_shear else deform_axis * 2
                     thermo_style_parts.append(f"v_cauchy_{axis_suffix}")
                elif stress in stress_map:
                    thermo_style_parts.append(f"v_{stress_map[stress]}")
        
        if mode == "Temperature" and output_config.get("add_target_to_thermo", False):
            thermo_style_parts.append("v_set_temp")

        averaged_quantities = output_config.get("averaged_quantities", [])
        
        if averaged_quantities:
            nevery = output_config.get("avg_nevery", 10)
            nrepeat = output_config.get("avg_nrepeat", 100)
            # Nfreq must always match thermo_freq to ensure output aligns with thermo logging
            nfreq = output_config.get("thermo_freq", 100)
            lines.append("# --- Time Averaging ---")
            
            processed_vars = set() 
            pressure_terms = {'press', 'pxx', 'pyy', 'pzz', 'pxy', 'pxz', 'pyz'}
            requested_press = [q for q in averaged_quantities if q in pressure_terms]
            
            if requested_press:
                lines.append("compute press_tensor all pressure thermo_temp")
                lines.append(f"fix ave_press all ave/time {nevery} {nrepeat} {nfreq} c_press_tensor[*]")
                
                lines.extend([
                    "variable press_avg equal f_ave_press", "variable pxx_avg equal f_ave_press[1]",
                    "variable pyy_avg equal f_ave_press[2]", "variable pzz_avg equal f_ave_press[3]",
                    "variable pxy_avg equal f_ave_press[4]", "variable pxz_avg equal f_ave_press[5]",
                    "variable pyz_avg equal f_ave_press[6]"
                ])
                
                for term in requested_press:
                    var_name = f"{term}_avg"
                    thermo_style_parts.append(f"v_{var_name}")
                    processed_vars.add(term)

            if 'temp' in averaged_quantities:
                lines.append("compute avg_temp_compute all temp")
                lines.append(f"fix avg_temp all ave/time {nevery} {nrepeat} {nfreq} c_avg_temp_compute")
                lines.append("variable temp_avg equal f_avg_temp")
                thermo_style_parts.append("v_temp_avg")
                processed_vars.add('temp')

            if 'ke' in averaged_quantities:
                lines.append("compute avg_ke_total_compute all reduce sum ke")
                lines.append(f"fix avg_ke all ave/time {nevery} {nrepeat} {nfreq} c_avg_ke_total_compute")
                lines.append("variable ke_avg equal f_avg_ke")
                thermo_style_parts.append("v_ke_avg")
                processed_vars.add('ke')

            if 'pe' in averaged_quantities:
                lines.append("compute avg_pe_total_compute all reduce sum pe")
                lines.append(f"fix avg_pe all ave/time {nevery} {nrepeat} {nfreq} c_avg_pe_total_compute")
                lines.append("variable pe_avg equal f_avg_pe")
                thermo_style_parts.append("v_pe_avg")
                processed_vars.add('pe')
            
            for item in averaged_quantities:
                if item in processed_vars: continue
                var_name = None
                
                if item in ['strain deformation direction', 'deformation direction']:
                    if mode == "Deformation":
                        if deform_axis == "vol":
                            axis_suffix = "xx"
                        else:
                            axis_suffix = deform_axis if is_shear else deform_axis * 2
                        var_name = f"strain_{axis_suffix}"
                elif item == 'stress deformation direction':
                    if mode == "Deformation":
                        if deform_axis == "vol":
                            axis_suffix = "xx"
                        else:
                            axis_suffix = deform_axis if is_shear else deform_axis * 2
                        var_name = f"cauchy_{axis_suffix}"
                elif item in strain_map:
                    if mode == "Deformation": var_name = strain_map[item]
                elif item in stress_map:
                    if mode == "Deformation": var_name = stress_map[item]
                
                if var_name:
                    if var_name not in processed_vars:
                        lines.append(f"fix avg_{var_name} all ave/time {nevery} {nrepeat} {nfreq} v_{var_name}")
                        lines.append(f"variable {var_name}_avg equal f_avg_{var_name}")
                        thermo_style_parts.append(f"v_{var_name}_avg")
                        processed_vars.add(var_name)
                        processed_vars.add(item)
                else:
                    lines.append(f"variable {item}_input equal {item}")
                    lines.append(f"fix ave_{item} all ave/time {nevery} {nrepeat} {nfreq} v_{item}_input")
                    lines.append(f"variable {item}_avg equal f_ave_{item}")
                    thermo_style_parts.append(f"v_{item}_avg")
                    processed_vars.add(item)
            
            lines.append("")

        seen = set()
        final_thermo_style_list = []
        for x in thermo_style_parts:
            if x not in seen:
                final_thermo_style_list.append(x)
                seen.add(x)

        final_thermo_style = " ".join(final_thermo_style_list)
        return lines, final_thermo_style

    def _format_float(self, f):
        """Formats a float to a string, avoiding unnecessary precision and trailing zeros."""
        return f'{f:.12g}'

    def _generate_bond_breakage_section(self, config):
        lines = ["#------------------------", "# Bond Breakage", "#------------------------"]
        nevery = config.get("nevery", 1)
        bondtype = config.get("bondtype", 1)
        rmax = self._format_float(config.get("rmax", 1.5))
        cmd = f"fix break_bonds all bond/break {nevery} {bondtype} {rmax}"
        if config.get("enable_prob", False):
            prob_fraction = self._format_float(config.get('prob_fraction', 0.1))
            prob_seed = config.get('prob_seed', 12345)
            cmd += f" prob {prob_fraction} {prob_seed}"
        lines.extend([cmd, ""])
        return lines
        
    def _generate_output_section(self, config, model_name, final_thermo_style):
        lines = []
        if config.get("enable_thermo", True):
            lines.extend([
                f"thermo {config.get('thermo_freq', 100)}",
                f"thermo_style custom {final_thermo_style}",
                "thermo_modify lost warn flush yes", ""
            ])
        if config.get("enable_trajectory", True):
            traj_format = config.get('traj_format', 'lammpstrj')
            if traj_format == "xyz":
                lines.extend([
                    f"dump trajectory all xyz {config.get('traj_freq', 100)} {model_name}.xyz",
                    "dump_modify trajectory append yes",
                    ""
                ])
            elif traj_format == "dcd":
                lines.extend([
                    f"dump trajectory all dcd {config.get('traj_freq', 100)} {model_name}.dcd",
                    "dump_modify trajectory append yes",
                    ""
                ])
            elif traj_format == "data":
                nocoeff_str = " nocoeff" if config.get("avoid_coefficients", True) else ""
                lines.extend([
                    "# Trajectory output configured as periodic data files via write_data in the main execution runs.",
                    f"if \"${{curstep}} == 0\" then \"write_data {model_name}_0.data{nocoeff_str}\"",
                    ""
                ])
            else:
                lines.extend([
                    f"dump trajectory all custom {config.get('traj_freq', 100)} {model_name}.{traj_format} {config.get('trj_output_items', 'id type x y z')}",
                    "dump_modify trajectory append yes",
                    ""
                ])
        if config.get("custom_dumps", ""):
            lines.extend(["# Custom Dumps", config.get("custom_dumps", ""), ""])
        return lines
        
    def generate_execution_script(self, root_simulation_dir, all_simulations):
        """Generate execution script for local processing."""
        try:
            import platform
            job_config = self.config.get("job_submission", {})
            os_type = job_config.get("os_type", "Auto-detect")
            
            is_unix = False
            if os_type == "Windows":
                is_unix = False
            elif os_type == "Unix/Linux":
                is_unix = True
            else:
                current_os = platform.system().lower()
                is_unix = current_os in ['linux', 'darwin']
            
            if is_unix:
                exec_path = os.path.join(root_simulation_dir, "local_run_all.sh")
                lines = ["#!/bin/bash", "echo 'Starting LAMMPS simulations...'", ""]
                command_prefix = "gnome-terminal -- bash -c '"
                command_suffix = "; exec bash'"
            else:
                exec_path = os.path.join(root_simulation_dir, "local_run_all.bat")
                lines = ["@echo off", "echo Starting LAMMPS simulations...", ""]
                command_prefix = "start cmd /k "
                command_suffix = ""

            local_lammps_cmd = job_config.get("local_lammps_cmd", "lmp")
            if job_config.get("local_multiprocessor", False):
                lammps_executable = job_config.get("local_lammps_executable", "lmp_mpi")
                num_processors = job_config.get("local_processors", 1)
                full_local_cmd = f"{local_lammps_cmd} -np {num_processors} {lammps_executable}"
            else:
                full_local_cmd = local_lammps_cmd

            log_file = job_config.get("log_file_name", "job.log")
            full_local_cmd += f" -log {log_file} -var curstep 0 -var maxtime 1e99"

            for sim in all_simulations:
                lines.extend([
                    f"echo 'Running: {sim['model_name']}'",
                    f"cd {sim['study_folder']}/{sim['system_folder']}",
                    f"{command_prefix}{full_local_cmd} -in {sim['model_name']}.in{command_suffix}",
                    f"cd ../../",
                    ""
                ])

            with open(exec_path, 'w', newline='\n') as f:
                f.write("\n".join(lines))
            
            if is_unix:
                os.chmod(exec_path, 0o755)
            
            self.generated_files.append(exec_path)
            return {"success": True}
        except Exception as e:
            return {"success": False, "message": f"Error generating local script: {str(e)}"}

    def generate_cluster_submission_script(self, root_simulation_dir, all_simulations):
        """Generate cluster job file and submission script"""
        try:
            job_config = self.config.get("job_submission", {})
            enable_restart = job_config.get("enable_restart", False)

            master_job_path = os.path.join(root_simulation_dir, "lammps_simulation.job")
            job_lines = [job_config.get("slurm_header", "#!/bin/bash\n#SBATCH --time=24:00:00"), ""]
            
            if enable_restart:
                hours = job_config.get("runtime_threshold_hours", 23)
                mins = job_config.get("runtime_threshold_minutes", 45)
                maxtime = hours * 3600 + mins * 60
                delete_restarts = "true" if job_config.get("delete_restart_files", False) else "false"

                job_lines.extend([
                    "input_file=$1",
                    "if [ -z \"$input_file\" ]; then echo 'Error: No input file'; exit 1; fi",
                    "MODEL_NAME=$(basename \"$input_file\" .in)",
                    "SIM_DIR=$(dirname \"$input_file\")",
                    "cd \"$SIM_DIR\"",
                    "curstep=0",
                    "if [ -d restart_files ] && [ \"$(ls -A restart_files)\" ]; then",
                    "  latest_restart=$(ls -v restart_files/${MODEL_NAME}.restart.* | tail -n 1)",
                    "  if [ -n \"$latest_restart\" ]; then",
                    "    curstep=$(basename \"$latest_restart\" | sed 's/.*\\.//')",
                    "  fi",
                    "fi",
                    f"module load {job_config.get('module_load', 'lammps')}",
                    f"{job_config.get('srun_cmd', 'srun')} {job_config.get('cluster_lammps_cmd', 'lmp')} -in \"$input_file\" -log none -var curstep $curstep -var maxtime {maxtime}",
                    "if [ \"${SLURM_PROCID:-0}\" -eq 0 ]; then",
                    "    if [ -f resubmit.flag ]; then",
                    "        rm resubmit.flag",
                    f"        {job_config.get('sbatch_cmd', 'sbatch')} \"../../lammps_simulation.job\" \"$input_file\"",
                    "    elif [ -f finished.flag ]; then",
                    f"        if [ \"{delete_restarts}\" = \"true\" ]; then rm -rf restart_files; rm restart.init; fi",
                    "        rm finished.flag",
                    "    fi",
                    "fi"
                ])
            else:
                job_lines.extend([
                    "input_file=$1",
                    "SIM_DIR=$(dirname \"$input_file\")",
                    f"module load {job_config.get('module_load', 'lammps')}",
                    f"cd \"$SIM_DIR\"",
                    f"{job_config.get('srun_cmd', 'srun')} {job_config.get('cluster_lammps_cmd', 'lmp')} -in \"$input_file\" -var curstep 0",
                ])
            
            with open(master_job_path, 'w', newline='\n') as f: f.write("\n".join(job_lines))
            os.chmod(master_job_path, 0o755)
            self.generated_files.append(master_job_path)

            cluster_script_path = os.path.join(root_simulation_dir, "cluster_run_all.sh")
            script_lines = ["#!/bin/bash", ""]
            for sim in all_simulations:
                script_lines.append(f"cd {sim['study_folder']}/{sim['system_folder']}")
                script_lines.append(f"{job_config.get('sbatch_cmd', 'sbatch')} --job-name=\"{sim['model_name']}\" \"../../lammps_simulation.job\" \"{sim['model_name']}.in\"")
                script_lines.append("cd ../../\n")
            
            script_lines.append(f"echo \"{len(all_simulations)} jobs have been submitted\"")
            
            with open(cluster_script_path, 'w', newline='\n') as f: f.write("\n".join(script_lines))
            os.chmod(cluster_script_path, 0o755)
            self.generated_files.append(cluster_script_path)

            return {"success": True}
        except Exception as e:
            return {"success": False, "message": f"Error generating cluster scripts: {str(e)}"}

    def generate_base_settings_file(self, root_simulation_dir):
        """Generate base_input.in file with common LAMMPS configuration"""
        try:
            config = self.config.get("system", {})
            lines = [
                "# Base LAMMPS Settings",
                f"units {config.get('units', 'metal')}",
                f"atom_style {config.get('atom_style', 'atomic')}",
                "dimension 3",
                f"boundary p p p",
                "", f"timestep {config.get('timestep', 0.001)}",
                ""
            ]
            custom_commands = config.get("custom_commands", "")
            if custom_commands:
                lines.extend(["# Custom Commands", custom_commands, ""])

            lines.extend([
                "# Strain and Stress Variables",
                "variable strain_xx equal (lx-v_L0x)/v_L0x",
                "variable strain_yy equal (ly-v_L0y)/v_L0y",
                "variable strain_zz equal (lz-v_L0z)/v_L0z",
                "variable strain_xy equal xy/v_L0y",
                "variable strain_xz equal xz/v_L0z",
                "variable strain_yz equal yz/v_L0z",
                f"variable cauchy_xx equal -(pxx-v_base_pressure)",
                f"variable cauchy_yy equal -(pyy-v_base_pressure)",
                f"variable cauchy_zz equal -(pzz-v_base_pressure)",
                "variable cauchy_xy equal -pxy",
                "variable cauchy_xz equal -pxz",
                "variable cauchy_yz equal -pyz",
                "variable hydrostatic equal (v_cauchy_xx+v_cauchy_yy+v_cauchy_zz)/3",
                'variable vMises equal "sqrt(0.5*((v_cauchy_xx-v_cauchy_yy)^2+(v_cauchy_yy-v_cauchy_zz)^2+(v_cauchy_zz-v_cauchy_xx)^2+6*(v_cauchy_xy^2+v_cauchy_yz^2+v_cauchy_xz^2)))"',
                ""
            ])

            base_settings_file = os.path.join(root_simulation_dir, "base_input.in")
            with open(base_settings_file, 'w') as f: f.write("\n".join(lines))
            self.generated_files.append(base_settings_file)
            return {"success": True}
        except Exception as e:
            return {"success": False, "message": f"Error generating base settings: {str(e)}"}
        
    def read_units_from_data_file(self, data_file):
        """Read units from a LAMMPS data file."""
        try:
            with open(data_file, 'r') as f:
                first_line = f.readline().strip()
                if "units" in first_line:
                    return first_line.split("units")[-1].strip().split()[0]
        except Exception:
            pass
        return None
