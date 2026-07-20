#!/usr/bin/env python3
"""
LAMMPS Script Generator

Handles the generation of LAMMPS input scripts and cluster job files
based on user configuration with support for symmetric wall movement,
engineering strain (tensile and shear), proper units handling, 
and structured file generation.

This version includes a robust, flag-based restart and predictive
termination system for HPC cluster environments.
Supports multiple data sets and studies.
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

class LammpsScriptGenerator:
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
            # Fallback to legacy single path if system_sets is missing (should not happen with new GUI)
            system_path = system_config.get("system_path", "")
            if not system_path:
                return {"success": False, "message": "No data sets defined."}
            system_sets = [{
                "system_path": system_path,
                "data_file_extensions": system_config.get("data_file_extensions", [".data"]),
                "use_potential_file": system_config.get("use_potential_file", False),
                "potential_file": system_config.get("potential_file", ""),
                "potential_source": system_config.get("potential_source", "file"),
                "potential_content": system_config.get("potential_content", ""),
                "potential_position": system_config.get("potential_position", "after"),
                "is_enabled": True
            }]

        validated_sets = []
        for i, s_set in enumerate(system_sets):
            # Only validate enabled sets
            if not s_set.get("is_enabled", True):
                continue

            path = s_set.get("system_path", "")
            if not path:
                return {"success": False, "message": f"System path not specified for Data Set {i+1}"}
            
            if not os.path.exists(path):
                return {"success": False, "message": f"Path does not exist for Data Set {i+1}: {path}"}

            # Resolve files for this set
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
            
            # Validate potential if enabled for this set
            if s_set.get("use_potential_file", False):
                source = s_set.get("potential_source", "file")
                if source == "file":
                    p_file = s_set.get("potential_file", "")
                    if not p_file or not os.path.exists(p_file):
                        return {"success": False, "message": f"Potential file missing or invalid for Data Set {i+1}"}
                elif source == "text":
                    if not s_set.get("potential_content", "").strip():
                        return {"success": False, "message": f"Potential commands missing for Data Set {i+1}"}

            # Determine base name for this set
            # If we have multiple system sets in the config, use the tab name (ConfigXX/VariantXX)
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

        # 3. Check Units Consistency (Warning only - across all active files)
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
        
        # 5. Validate Output Configuration
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
            
            # --- PHASE 1: VALIDATION ---
            val_result = self.validate_configuration()
            if not val_result["success"]:
                return val_result
            
            # Extract data derived during validation
            warnings = val_result["warnings"]
            validated_sets = val_result["validated_sets"]
            
            # Retrieve configs
            system_config = self.config.get("system", {})
            output_config = self.config.get("output", {})
            deform_studies = self.config.get("multistudy", {}).get("deform_studies", [])

            # Determine naming convention
            total_sets_in_ui = len(system_config.get("system_sets", []))
            use_naming_prefix = total_sets_in_ui > 1

            # --- PHASE 2: GENERATION (Write Operations) ---
            
            output_path = output_config.get("output_path", "")
            if not output_path:
                # Default to directory of first data file if not set
                output_path = os.path.dirname(validated_sets[0]["files"][0])
            
            root_simulation_dir = output_path
            os.makedirs(root_simulation_dir, exist_ok=True)
            
            # Create _input_files folder
            data_files_folder = os.path.join(root_simulation_dir, "_input_files")
            os.makedirs(data_files_folder, exist_ok=True)
            
            # Generate base settings file
            base_settings_result = self.generate_base_settings_file(root_simulation_dir)
            if not base_settings_result["success"]:
                return base_settings_result
            
            all_simulations = [] # To track all generated simulations for batch scripts
            
            # Shared potential reference if syncing is enabled
            synced_potential_ref = None
            synced_potential_processed = False

            # Process each Data Set
            for set_idx, v_set in enumerate(validated_sets):
                set_config = v_set["config"]
                set_files = v_set["files"]
                set_base_name = v_set["name"]
                
                # Handle potential for this set
                potential_ref = None
                if set_config.get("use_potential_file", False):
                    # Check if we should use a shared synced potential
                    if set_config.get("sync_potential", False):
                        if not synced_potential_processed:
                            # Generate the shared potential once
                            source = set_config.get("potential_source", "file")
                            if source == "file":
                                potential_file = set_config.get("potential_file", "")
                                if potential_file and os.path.exists(potential_file):
                                    unique_pot_name = f"synced_{Path(potential_file).name}"
                                    potential_dest = os.path.join(data_files_folder, unique_pot_name)
                                    shutil.copy2(potential_file, potential_dest)
                                    synced_potential_ref = f"_input_files/{unique_pot_name}"
                            elif source == "text":
                                potential_content = set_config.get("potential_content", "")
                                unique_pot_name = "synced_custom.potential"
                                potential_dest = os.path.join(data_files_folder, unique_pot_name)
                                with open(potential_dest, 'w') as f:
                                    f.write(potential_content)
                                synced_potential_ref = f"_input_files/{unique_pot_name}"
                            synced_potential_processed = True
                        
                        potential_ref = synced_potential_ref
                    else:
                        # Standard per-variant potential
                        source = set_config.get("potential_source", "file")
                        prefix = f"{set_base_name}_" if use_naming_prefix else ""
                        if source == "file":
                            potential_file = set_config.get("potential_file", "")
                            if potential_file and os.path.exists(potential_file):
                                unique_pot_name = f"{prefix}{Path(potential_file).name}"
                                potential_dest = os.path.join(data_files_folder, unique_pot_name)
                                shutil.copy2(potential_file, potential_dest)
                                potential_ref = f"_input_files/{unique_pot_name}"
                        elif source == "text":
                            potential_content = set_config.get("potential_content", "")
                            unique_pot_name = f"{prefix}custom.potential"
                            potential_dest = os.path.join(data_files_folder, unique_pot_name)
                            with open(potential_dest, 'w') as f:
                                f.write(potential_content)
                            potential_ref = f"_input_files/{unique_pot_name}"

                # Generate scripts for each study and file combination
                for study in deform_studies:
                    study_name = study.get("name", "study")
                    # Apply naming convention
                    study_folder_name = f"{set_base_name}_{study_name}" if use_naming_prefix else study_name
                    study_folder = os.path.join(root_simulation_dir, study_folder_name)
                    os.makedirs(study_folder, exist_ok=True)

                    for system_file in set_files:
                        system_name = Path(system_file).stem
                        
                        # Copy data file with variant prefix
                        prefix = f"{set_base_name}_" if use_naming_prefix else ""
                        unique_data_name = f"{prefix}{system_name}.data"
                        data_file_dest = os.path.join(data_files_folder, unique_data_name)
                        shutil.copy2(system_file, data_file_dest)
                        data_file_relative_path = f"_input_files/{unique_data_name}"

                        # Create simulation-specific folder
                        sim_folder = os.path.join(study_folder, system_name)
                        os.makedirs(sim_folder, exist_ok=True)
                        
                        # Generate script
                        model_name = f"{study_folder_name}_{system_name}"
                        
                        result = self.generate_single_script(
                            system_file, model_name, study, 
                            sim_folder, data_file_relative_path,
                            potential_ref=potential_ref,
                            set_config=set_config
                        )
                        
                        if not result["success"]:
                            return result
                            
                        all_simulations.append({
                            "study_folder": study_folder_name,
                            "system_folder": system_name,
                            "model_name": model_name
                        })
            
            # Generate execution scripts using the new all_simulations list
            exec_script_result = self.generate_execution_script(root_simulation_dir, all_simulations)
            if not exec_script_result["success"]:
                return exec_script_result
            
            cluster_script_result = self.generate_cluster_submission_script(root_simulation_dir, all_simulations)
            if not cluster_script_result["success"]:
                return cluster_script_result
            
            # Save settings to JSON file
            settings_result = self.save_settings_to_json(root_simulation_dir)
            if not settings_result["success"]:
                return settings_result
            
            # Final message
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
                    
        # If we found no units, or only one type of unit, we are consistent
        if len(defined_units) <= 1:
            return {"consistent": True, "units": list(defined_units)[0] if defined_units else None}
            
        # If we reached here, we have conflicting definitions (e.g. metal AND real)
        return {
            "consistent": False, 
            "message": f"Units mismatch detected in source files: {defined_units}. The generator will proceed using the units defined in the System Configuration tab ('{self.config.get('system', {}).get('units', 'unknown')}'). Please check your input data files before running the simulations!"
        }
        
    def generate_single_script(self, data_file, model_name, deform_study, output_dir, data_file_dest, potential_ref=None, set_config=None):
        """Generate a single LAMMPS input script"""
        try:
            script_filename = os.path.join(output_dir, f"{model_name}.in")
            script_content = self.generate_script_content(data_file_dest, model_name, deform_study, potential_ref, set_config)
            with open(script_filename, 'w') as f:
                f.write(script_content)
            self.generated_files.append(script_filename)
            return {"success": True, "message": f"Script generated: {script_filename}", "script_file": script_filename}
        except Exception as e:
            return {"success": False, "message": f"Error generating script: {str(e)}"}

    def generate_script_content(self, data_file, model_name, deform_study, potential_ref=None, set_config=None):
        """Generate the content of a LAMMPS input script"""
        try:
            system_config = self.config.get("system", {})
            if set_config is None:
                set_config = system_config
                
            fixes_config = self.config.get("fixes", {})
            output_config = self.config.get("output", {}).copy()
            job_submission_config = self.config.get("job_submission", {})
            enable_restart = job_submission_config.get("enable_restart", False)
            restart_freq = job_submission_config.get("restart_freq", 100000)
            max_steps = deform_study.get("max_steps", 0)

            script_lines = [
                f"# {model_name}.in",
                f"# Generated by LAMMPS Input Script Generator on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", "",
                "#------------------------", "# Base settings", "#------------------------", "include ../../base_input.in", ""
            ]

            # Check for sine segments to add global sine variables
            has_sine_segment = any(s.get("type") == "sine" for s in deform_study.get("segments", []))
            if has_sine_segment:
                script_lines.extend([
                    "#------------------------",
                    "# Global Sine Variables",
                    "#------------------------",
                    "variable started equal 1",
                    "variable sinState equal 0",
                    ""
                ])

            # Prepare potential include line
            potential_include_line = ""
            potential_position = set_config.get("potential_position", "after")
            
            if potential_ref:
                potential_include_line = f"include ../../{potential_ref}"

            if potential_include_line and potential_position == "before":
                script_lines.extend([potential_include_line, ""])

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
            
            # Add potential after read_data if configured
            if potential_include_line and potential_position == "after":
                script_lines.extend([potential_include_line, ""])
            # --- New logic for preserving initial box dimensions ---
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

            deform_axis = deform_study.get("deform_axis", "x")
            mode = deform_study.get("mode", "Deformation")
            is_shear = deform_axis in ["xy", "xz", "yz"]
            ensemble_config = deform_study.get("ensemble", {})
            if (ensemble_config.get("ensemble") == "NPT" and ensemble_config.get("npt_aniso") == "tri") or is_shear:
                script_lines.extend(["change_box all triclinic", ""])

            points = deform_study.get("data_points", [])

            # --- Define base_pressure variable ---
            pressure = self._format_float(ensemble_config.get("pressure", 1.0))
            script_lines.extend([f"variable base_pressure equal {pressure}", ""])

            if mode == "Temperature":
                script_lines.extend(["#------------------------", "# Temperature Variables", "#------------------------"])
                initial_temp = points[0][1] if points else 300.0
                script_lines.extend([f"variable set_temp equal {initial_temp}", ""])

            # --- Initial Velocity (Moved BEFORE Fixes) ---
            if system_config.get("enable_velocity", True):
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

            # --- Fixes & Computes ---
            fixes_computes_lines, final_thermo_style = self._generate_fixes_computes_section(deform_study, output_config, fixes_config, mode, deform_axis, is_shear)
            if fixes_computes_lines:
                script_lines.extend(["#------------------------", "# Fixes & Computes", "#------------------------", *fixes_computes_lines])
            
            # Handle the new bond commands functionality - if the new field exists, use it
            bond_commands_config = deform_study.get("bond_commands", {})
            bond_commands_text = bond_commands_config.get("commands", "").strip()

            if bond_commands_text:  # If there are study-specific commands
                # Add the custom study-specific commands to the script
                script_lines.extend(["#------------------------", "# Study-specific Commands", "#------------------------"])
                # Split the commands by newlines and add each one
                for line in bond_commands_text.split('\n'):
                    line = line.strip()
                    if line and not line.startswith('#'):  # Skip empty lines and comments
                        script_lines.append(line)
                script_lines.append("")  # Add empty line for formatting

            # Handle backward compatibility for old bond breakage settings
            bond_breakage_config = deform_study.get("bond_breakage", {})
            if bond_breakage_config.get("enable_bond_breakage", False):
                script_lines.extend(self._generate_bond_breakage_section(bond_breakage_config))
            
            output_lines = self._generate_output_section(output_config, model_name, final_thermo_style)
            if output_lines:
                 script_lines.extend(["#------------------------", "# Output Settings", "#------------------------", *output_lines])
            
            script_lines.extend(["#===========================================================", "# Main Simulation Logic", "#===========================================================", ""])
            
            write_data_option = output_config.get("write_data_option", "At the end of the simulation")
            base_name = Path(data_file).stem
            write_data_filename = f"{base_name}_*.data"

            if enable_restart:
                execution_blocks = self._generate_execution_blocks(deform_study)
                user_handle_steps = {int(p[0]) for p in deform_study.get("data_points", []) if int(p[0]) > 0}

                script_lines.extend([
                    "# --- Timer and Maximum Time Setup for Predictive Quit ---",
                    "variable global_start_time timer",
					"variable chunk_start_time timer",
					"variable max_chunk_time equal 0.0",
					""
                ])
                script_lines.extend(["# --- Jump to correct segment based on restart step ---"])
                script_lines.append("label segment_distribution")
                restart_steps = sorted(list(set([block['start_step'] for block in execution_blocks])))
                for step in restart_steps:
                    block = next((b for b in execution_blocks if b['start_step'] == step), None)
                    if block: script_lines.append("if \"${curstep} == " + str(step) + "\" then \"jump SELF segment_" + str(block['user_segment_id']) + "_" + str(step) + "\"")

                if max_steps > 0:
                    script_lines.append("if \"${curstep} == " + str(int(max_steps)) + "\" then \"jump SELF end\"")
                
                script_lines.extend(["if \"${curstep} > 0\" then \"print 'ERROR: Restart step ${curstep} does not match any known segment start. Aborting.' ; quit\"", ""])

                # --- Main Execution Loop ---
                processed_sine_segments = set()
                for block in execution_blocks:
                    # Generate restart chunk if necessary
                    start_step = block['start_step']
                    if start_step > 0 and start_step % restart_freq == 0:
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

                    # If this is the first time we're seeing a sine segment, generate its init block.
                    segment_info = block.get("segment_info", {})
                    user_segment_id = block.get("user_segment_id")
                    if segment_info.get("type") == "sine" and user_segment_id not in processed_sine_segments:
                        
                        amp = self._format_float(segment_info.get('amplitude_strain', 0))
                        period = self._format_float(segment_info.get('period_steps', 0))
                        phase = self._format_float(segment_info.get('phase_shift_steps', 0))
                        ashift = self._format_float(segment_info.get('ashift_factor', 0))
                        
                        shear_dim_map = {'xy': 'y', 'xz': 'z', 'yz': 'z'}
                        if is_shear:
                            ref_len_var = f"v_L0{shear_dim_map[deform_axis]}"
                        else:
                            ref_len_var = f"v_L0{deform_axis}"

                        init_block = [
                            f"\n# --- Segment {user_segment_id} Init ---",
                            f"label segment_{user_segment_id}_init",
                            f"variable A equal {amp}*{ref_len_var}",
                            f"variable Sp equal {period}",
                            f"variable phaseShift equal {phase}",
                            f"variable Ashift equal {ashift}*v_A",
                            'variable displace equal "v_A * sin(2*PI * (step-v_phaseShift)/v_Sp) + v_Ashift - v_sinState"',
                            'variable rate equal "2*PI/v_Sp * v_A * cos(2*PI * (step-v_phaseShift)/v_Sp)"',
                            'if "$(v_started) == 1" then &',
                            '  "variable started equal 0" &',
                            '  "jump SELF segment_distribution"'
                        ]
                        script_lines.extend(init_block)
                        processed_sine_segments.add(user_segment_id)
                    
                    script_lines.extend(self._generate_segment_block(block, deform_study, system_config, is_shear, has_sine_segment))

                    if write_data_option == "After each deformation/temperature step":
                        if block['end_step'] in user_handle_steps:
                            script_lines.extend(["", f"# Write data at handle at step {block['end_step']}", f"write_data {write_data_filename}"])

                if max_steps > 0 and max_steps % restart_freq == 0:
                    script_lines.extend([
                        "\n# --- Final Chunk Check ---",
                        "variable current_time timer",
                        "variable current_chunk_time equal $(v_current_time - v_chunk_start_time)",
                        "if \"${current_chunk_time} > ${max_chunk_time}\" then \"variable max_chunk_time equal ${current_chunk_time}\"",
                        f"write_restart restart_files/{model_name}.restart.*"
                    ])

                if execution_blocks: script_lines.append(f"\njump SELF end")
            
            else:
                for i in range(len(points) - 1):
                    p1, p2 = points[i], points[i+1]
                    if int(p1[0]) >= int(p2[0]): continue
                    block_info = { "start_step": int(p1[0]), "end_step": int(p2[0]), "sub_start_y": p1[1], "sub_end_y": p2[1], "user_segment_id": i + 1 }
                    script_lines.extend(self._generate_segment_block(block_info, deform_study, system_config, is_shear, has_sine_segment))
                    if write_data_option == "After each deformation/temperature step":
                        script_lines.extend(["", f"# Write data after segment {i+1}", f"write_data {write_data_filename}"])

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

    def _generate_execution_blocks(self, deform_study):
        """Creates a unified list of execution blocks based on user handles and restart frequency."""
        job_config = self.config.get("job_submission", {})
        restart_freq = job_config.get("restart_freq", 100000)
        points = deform_study.get("data_points", []).copy()
        segments = deform_study.get("segments", [])
        max_steps = deform_study.get("max_steps", 0)

        if not points: return []
        if int(points[0][0]) != 0: points.insert(0, [0, points[0][1]])
        
        event_steps = {0, int(max_steps)}
        for p in points: event_steps.add(int(p[0]))
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

            block_info = {
                "start_step": start_step,
                "end_step": end_step,
                "user_segment_id": user_segment_idx + 1,
                "segment_info": segment_info,
                "write_restart_at_end": (end_step % restart_freq == 0 and end_step > 0)
            }

            if segment_info.get('type') == 'line':
                p1 = points[user_segment_idx]
                p2 = points[user_segment_idx + 1] if user_segment_idx + 1 < len(points) else p1
                start_step_orig, end_step_orig = int(p1[0]), int(p2[0])
                start_y_orig, end_y_orig = p1[1], p2[1]
                total_duration = end_step_orig - start_step_orig
                
                if total_duration > 0:
                    sub_start_y = start_y_orig + (end_y_orig - start_y_orig) * ((start_step - start_step_orig) / total_duration)
                    sub_end_y = start_y_orig + (end_y_orig - start_y_orig) * ((end_step - start_step_orig) / total_duration)
                else:
                    sub_start_y = start_y_orig
                    sub_end_y = end_y_orig
                
                block_info["sub_start_y"] = sub_start_y
                block_info["sub_end_y"] = sub_end_y

            blocks.append(block_info)
        return blocks

    def _generate_segment_block(self, block_info, deform_study, system_config, is_shear, has_sine_segment):
        """Generates the core physics commands for a single execution block or user segment."""
        lines = []
        start_step, end_step = block_info['start_step'], block_info['end_step']
        duration = end_step - start_step
        
        mode = deform_study.get("mode", "Deformation")
        deform_axis = deform_study.get("deform_axis", "x")
        ensemble_config = deform_study.get("ensemble", {})
        ensemble = ensemble_config.get("ensemble", "NVT")
        remap_val = deform_study.get("remap", "x")
        
        segment_info = block_info.get("segment_info", {'type': 'line'})
        is_strain_recovery = segment_info.get('strain_recovery', False)

        # Pre-calculate common variables used in all blocks
        temp = self._format_float(ensemble_config.get("temperature", 300.0))
        pressure = self._format_float(ensemble_config.get("pressure", 1.0))
        damping = self._format_float(system_config.get("damping_factor", 100.0))
        
        temp_start_ens = temp
        temp_end_ens = temp
        if mode == "Temperature":
             temp_start_ens = self._format_float(block_info.get('sub_start_y', temp))
             temp_end_ens = self._format_float(block_info.get('sub_end_y', temp))

        lines.append(f"\n# --- Segment {block_info['user_segment_id']}: from step {start_step} to {end_step} ---")
        lines.append(f"label segment_{block_info['user_segment_id']}_{start_step}")

        if has_sine_segment and segment_info.get('type') == 'line':
            lines.append("variable started equal 0")

        if segment_info.get('type') == 'sine' and mode == "Deformation":
            lines.append(f"if \"$(v_started) == 1\" then \"jump SELF segment_{block_info['user_segment_id']}_init\"")
            lines.append(f"variable sinState equal $(v_A * sin(2*PI * (step-v_phaseShift)/v_Sp) + v_Ashift)")
            lines.append(f"fix deform all deform 1 {deform_axis} variable v_displace v_rate units box remap {remap_val} flip no")

        elif mode == "Deformation": # This is now the 'line' segment case
            # Determine effective lateral settings for this segment
            study_lateral_settings = ensemble_config.get("lateral_contraction", {})
            segment_lateral_overrides = segment_info.get('lateral_overrides', {})
            
            effective_lateral_settings = study_lateral_settings.copy()
            for ax, override_val in segment_lateral_overrides.items():
                effective_lateral_settings[ax] = override_val

            is_strain_recovery = segment_info.get('strain_recovery', False)
            
            # Sub-segment Y values
            sub_start_y, sub_end_y = block_info['sub_start_y'], block_info['sub_end_y']
            final_target_y = self._format_float(sub_end_y)

            # --- Strain Recovery Logic ---
            if is_strain_recovery:
                # No fix deform for strain recovery
                # Force NPT for all axes (including deform axis)
                npt_parts = []
                # Always put deform_axis in NPT
                # For shear, target pressure/stress is 0. For tensile, it's the system pressure.
                target_p = "0.0" if is_shear else pressure
                npt_parts.append(f"{deform_axis} {target_p} {target_p} $({1000}*dt)")

                all_axes = ['x', 'y', 'z']
                # Add control for non-deforming normal axes based on effective_lateral_settings
                for ax in all_axes:
                    if ax != deform_axis and effective_lateral_settings.get(ax) == "free (NPT)":
                        npt_parts.append(f"{ax} {pressure} {pressure} $({1000}*dt)")
                
                # Handle Tilt/Shear controls for NPT recovery
                npt_aniso_study = ensemble_config.get("npt_aniso", "aniso")
                npt_aniso_effective = "tri" if is_shear else npt_aniso_study

                if npt_aniso_effective == "tri":
                    for tilt in ['xy', 'xz', 'yz']:
                        if tilt != deform_axis:
                            npt_parts.append(f"{tilt} 0.0 0.0 $({1000}*dt)")
                
                lines.append(f"fix ensemble all npt temp {temp_start_ens} {temp_end_ens} $({damping}*dt) {' '.join(npt_parts)} flip no")
            
            # --- Normal Deformation Logic ---
            else:
                # Existing fix deform logic
                if segment_info.get('type') == 'sine':
                    lines.append(f"if \"$(v_started) == 1\" then \"jump SELF segment_{block_info['user_segment_id']}_init\"")
                    lines.append(f"variable sinState equal $(v_A * sin(2*PI * (step-v_phaseShift)/v_Sp) + v_Ashift)")
                    lines.append(f"fix deform all deform 1 {deform_axis} variable v_displace v_rate units box remap {remap_val} flip no")
                else: # Line segment
                    if is_shear:
                        lines.append(f"variable tilt_target equal \"{final_target_y} * v_L0{deform_axis[1]}\"")
                        lines.append(f"fix deform all deform 1 {deform_axis} final ${{tilt_target}} units box remap {remap_val} flip no")
                    else:
                        deform_scenario = deform_study.get("deform_scenario", "symmetric")
                        if deform_scenario == "shift hi, fix lo":
                            lines.extend([f'variable {deform_axis}lo_target equal v_{deform_axis}lo0', f'variable {deform_axis}hi_target equal "v_{deform_axis}hi0 + (v_L0{deform_axis} * {final_target_y})"'])
                        elif deform_scenario == "shift lo, fix hi":
                            lines.extend([f'variable {deform_axis}lo_target equal "v_{deform_axis}lo0 - (v_L0{deform_axis} * {final_target_y})"', f"variable {deform_axis}hi_target equal v_{deform_axis}hi0"])
                        else: # symmetric
                            lines.extend([f'variable {deform_axis}lo_target equal "v_{deform_axis}lo0 - (v_L0{deform_axis} * {final_target_y}) / 2"', f'variable {deform_axis}hi_target equal "v_{deform_axis}hi0 + (v_L0{deform_axis} * {final_target_y}) / 2"'])
                        lines.append(f"fix deform all deform 1 {deform_axis} final ${{{deform_axis}lo_target}} ${{{deform_axis}hi_target}} units box remap {remap_val} flip no")
                
                # Ensemble for normal deformation
                free_axes = [ax for ax, setting in effective_lateral_settings.items() if setting == "free (NPT)"]

                if not free_axes:
                    # No free lateral axes -> NVT
                    lines.append(f"fix ensemble all nvt temp {temp_start_ens} {temp_end_ens} $({damping}*dt) flip no")
                else:
                    # At least one free axis -> NPT
                    npt_parts = []
                    
                    # Add control for free normal axes
                    for ax in free_axes:
                        npt_parts.append(f"{ax} {pressure} {pressure} $({1000}*dt)")
                    
                    # Handle Tilt/Shear controls
                    npt_aniso_study = ensemble_config.get("npt_aniso", "aniso")
                    npt_aniso_effective = "tri" if is_shear else npt_aniso_study
                    
                    if npt_aniso_effective == "tri":
                        for tilt in ['xy', 'xz', 'yz']:
                            if tilt != deform_axis:
                                npt_parts.append(f"{tilt} 0.0 0.0 $({1000}*dt)")

                    lines.append(f"fix ensemble all npt temp {temp_start_ens} {temp_end_ens} $({damping}*dt) {' '.join(npt_parts)} flip no")

        elif mode == "Temperature":
            sub_start_y, sub_end_y = block_info['sub_start_y'], block_info['sub_end_y']
            slope = (sub_end_y - sub_start_y) / duration if duration > 0 else 0
            lines.extend([f"variable ramp_slope equal {self._format_float(slope)}", f"variable set_temp equal \"{self._format_float(sub_start_y)} + (step - {start_step}) * v_ramp_slope\""])

            if ensemble == "NVT":
                lines.append(f"fix ensemble all nvt temp {temp_start_ens} {temp_end_ens} $({damping}*dt) flip no")
            else: # NPT
                npt_aniso = ensemble_config.get("npt_aniso", "iso")
                lines.append(f"fix ensemble all npt temp {temp_start_ens} {temp_end_ens} $({damping}*dt) {npt_aniso} {pressure} {pressure} $(1000*dt) flip no")

        lines.append(f"run {int(duration)}")
        
        if mode == "Deformation" and not is_strain_recovery: lines.append("unfix deform")
        lines.append("unfix ensemble")
        
        return lines

    def _generate_fixes_computes_section(self, deform_study, output_config, fixes_config, mode, deform_axis, is_shear):
        """Generates the full string for the Fixes & Computes section, including time-averaging."""
        lines = []
        
        # 1. Base Thermo Style
        base_thermo_style = output_config.get("thermo_style", "step temp press")
        thermo_style_parts = base_thermo_style.split()
        
        ensemble_config = deform_study.get("ensemble", {})
        
        # Define Maps
        strain_map = {'εxx': 'strain_xx', 'εyy': 'strain_yy', 'εzz': 'strain_zz', 
                      'εxy': 'strain_xy', 'εxz': 'strain_xz', 'εyz': 'strain_yz'}
        stress_map = {'σxx': 'cauchy_xx', 'σyy': 'cauchy_yy', 'σzz': 'cauchy_zz', 
                      'σxy': 'cauchy_xy', 'σxz': 'cauchy_xz', 'σyz': 'cauchy_yz', 
                      'von Mises': 'vMises', 'hydrostatic': 'hydrostatic'}

        # --- Add selected strains/stresses to thermo output ---
        if mode == "Deformation":
            for strain in output_config.get("eng_strains", []):
                # Handle distinct label
                if strain == 'strain deformation direction':
                    axis_suffix = deform_axis if is_shear else deform_axis * 2
                    thermo_style_parts.append(f"v_strain_{axis_suffix}")
                elif strain == 'deformation direction': # Legacy fallback
                    axis_suffix = deform_axis if is_shear else deform_axis * 2
                    thermo_style_parts.append(f"v_strain_{axis_suffix}")
                elif strain in strain_map:
                    thermo_style_parts.append(f"v_{strain_map[strain]}")
            
            for stress in output_config.get("cauchy_stresses", []):
                # Handle distinct label
                if stress == 'stress deformation direction':
                     axis_suffix = deform_axis if is_shear else deform_axis * 2
                     thermo_style_parts.append(f"v_cauchy_{axis_suffix}")
                elif stress == 'deformation direction': # Legacy fallback
                     axis_suffix = deform_axis if is_shear else deform_axis * 2
                     thermo_style_parts.append(f"v_cauchy_{axis_suffix}")
                elif stress in stress_map:
                    thermo_style_parts.append(f"v_{stress_map[stress]}")
        
        # --- Add target temperature if in Temperature mode ---
        if mode == "Temperature" and output_config.get("add_target_to_thermo", False):
            thermo_style_parts.append("v_set_temp")

        # --- Time Averaging Logic ---
        averaged_quantities = output_config.get("averaged_quantities", [])
        
        if averaged_quantities:
            nevery = output_config.get("avg_nevery", 10)
            nrepeat = output_config.get("avg_nrepeat", 100)
            nfreq = nevery * nrepeat
            lines.append("# --- Time Averaging ---")
            
            # Keep track of variables we've already processed to avoid duplicates
            processed_vars = set() 

            # 1. Pressure Tensor Terms
            pressure_terms = {'press', 'pxx', 'pyy', 'pzz', 'pxy', 'pxz', 'pyz'}
            requested_press = [q for q in averaged_quantities if q in pressure_terms]
            
            if requested_press:
                lines.append("compute press_tensor all pressure thermo_temp")
                lines.append(f"fix ave_press all ave/time {nevery} {nrepeat} {nfreq} c_press_tensor[*]")
                
                lines.extend([
                    "variable press_avg equal f_ave_press",
                    "variable pxx_avg equal f_ave_press[1]",
                    "variable pyy_avg equal f_ave_press[2]",
                    "variable pzz_avg equal f_ave_press[3]",
                    "variable pxy_avg equal f_ave_press[4]",
                    "variable pxz_avg equal f_ave_press[5]",
                    "variable pyz_avg equal f_ave_press[6]"
                ])
                
                for term in requested_press:
                    var_name = f"{term}_avg"
                    thermo_style_parts.append(f"v_{var_name}")
                    processed_vars.add(term)

            # 2. Standard Computes (Temp, KE, PE)
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
            
            # 3. Individual Strains, Stresses, and Generic Quantities
            for item in averaged_quantities:
                # Skip if already handled by complex logic above
                if item in processed_vars: continue
                
                var_name = None
                
                # Check Strains
                if item == 'strain deformation direction':
                    if mode == "Deformation":
                        axis_suffix = deform_axis if is_shear else deform_axis * 2
                        var_name = f"strain_{axis_suffix}"
                # Check Stresses
                elif item == 'stress deformation direction':
                    if mode == "Deformation":
                        axis_suffix = deform_axis if is_shear else deform_axis * 2
                        var_name = f"cauchy_{axis_suffix}"
                # Legacy fallback
                elif item == 'deformation direction':
                    if mode == "Deformation":
                        axis_suffix = deform_axis if is_shear else deform_axis * 2
                        var_name = f"strain_{axis_suffix}"
                # Maps
                elif item in strain_map:
                    if mode == "Deformation": var_name = strain_map[item]
                elif item in stress_map:
                    if mode == "Deformation": var_name = stress_map[item]
                
                # If identified as a specific Strain/Stress variable
                if var_name:
                    if var_name not in processed_vars:
                        lines.append(f"fix avg_{var_name} all ave/time {nevery} {nrepeat} {nfreq} v_{var_name}")
                        lines.append(f"variable {var_name}_avg equal f_avg_{var_name}")
                        thermo_style_parts.append(f"v_{var_name}_avg")
                        processed_vars.add(var_name)
                        processed_vars.add(item) # Mark original text as processed
                else:
                    # 4. Generic Fallback for Standard Keywords (e.g. density, vol, step, etc.)
                    # Create a variable to wrap the keyword so it can be averaged
                    lines.append(f"variable {item}_input equal {item}")
                    lines.append(f"fix ave_{item} all ave/time {nevery} {nrepeat} {nfreq} v_{item}_input")
                    lines.append(f"variable {item}_avg equal f_ave_{item}")
                    thermo_style_parts.append(f"v_{item}_avg")
                    processed_vars.add(item)
            
            lines.append("")

        # Remove duplicates from thermo_style while preserving order
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
            lines.extend([
                f"dump trajectory all custom {config.get('traj_freq', 100)} {model_name}.{config.get('traj_format', 'lammpstrj')} {config.get('trj_output_items', 'id type x y z')}",
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

            # 1. Master Job File
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
                    f"{job_config.get('srun_cmd', 'srun')} {job_config.get('cluster_lammps_cmd', 'lmp')} -in \"$input_file\"",
                ])
            
            with open(master_job_path, 'w', newline='\n') as f: f.write("\n".join(job_lines))
            os.chmod(master_job_path, 0o755)
            self.generated_files.append(master_job_path)

            # 2. Submission Script
            cluster_script_path = os.path.join(root_simulation_dir, "cluster_run_all.sh")
            script_lines = ["#!/bin/bash", ""]
            for sim in all_simulations:
                script_lines.append(f"cd {sim['study_folder']}/{sim['system_folder']}")
                script_lines.append(f"{job_config.get('sbatch_cmd', 'sbatch')} --job-name=\"{sim['model_name']}\" \"../../lammps_simulation.job\" \"{sim['model_name']}.in\"")
                script_lines.append("cd ../../\n")
            
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
                f"variable cauchy_xx equal -(pxx-v_base_pressure)",
                f"variable cauchy_yy equal -(pyy-v_base_pressure)",
                f"variable cauchy_zz equal -(pzz-v_base_pressure)",
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
