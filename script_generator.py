#!/usr/bin/env python3
"""
LAMMPS Script Generator

Handles the generation of LAMMPS input scripts and cluster job files
based on user configuration with support for symmetric wall movement,
engineering strain (tensile and shear), proper units handling, 
and structured file generation.

This version includes a robust, flag-based restart and predictive
termination system for HPC cluster environments.
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
        
    def generate_all_scripts(self):
        """Generate all necessary scripts based on configuration"""
        try:
            self.generated_files = []
            
            # Validate configuration structure
            if not isinstance(self.config, dict):
                return {"success": False, "message": "Invalid configuration: not a dictionary"}
            
            # Get system path and determine if it's single file or directory
            system_config = self.config.get("system", {})
            if not isinstance(system_config, dict):
                return {"success": False, "message": "Invalid system configuration"}
                
            system_path = system_config.get("system_path", "")
            if not system_path:
                return {"success": False, "message": "System path not specified"}
            
            if not os.path.exists(system_path):
                return {"success": False, "message": f"System path does not exist: {system_path}"}
            
            # Determine system files
            if os.path.isfile(system_path):
                system_files = [system_path]
                is_multi_system = False
            elif os.path.isdir(system_path):
                data_extensions = self.config.get("system", {}).get("data_file_extensions", [".data"])
                system_files = []
                for ext in data_extensions:
                    system_files.extend(glob.glob(os.path.join(system_path, f"*{ext}")))
                
                is_multi_system = len(system_files) > 1
                if not system_files:
                    return {"success": False, "message": f"No data files with extensions {data_extensions} found in the specified directory."}
            else:
                return {"success": False, "message": "Invalid system path."}
            
            # Check units consistency if multi-system
            if is_multi_system:
                units_check = self.check_units_consistency(system_files)
                if not units_check["consistent"]:
                    return {"success": False, "message": units_check["message"]}
            
            # Get deformation studies
            deform_studies = self.config.get("multistudy", {}).get("deform_studies", [])
            if not deform_studies:
                return {"success": False, "message": "No deformation studies defined."}
            
            # Validate each deformation study
            for i, study in enumerate(deform_studies):
                if not isinstance(study, dict):
                    return {"success": False, "message": f"Invalid deformation study at index {i}"}
                
                required_fields = ["name", "data_points", "max_steps", "min_strain", "max_strain"]
                for field in required_fields:
                    if field not in study:
                        return {"success": False, "message": f"Missing field '{field}' in deformation study '{study.get('name', f'study_{i}')}'"}
            
            # Create output directory structure
            output_config = self.config.get("output", {})
            if not isinstance(output_config, dict):
                return {"success": False, "message": "Invalid output configuration"}
                
            output_path = output_config.get("output_path", "")
            if not output_path:
                output_path = os.path.dirname(system_files[0])
            
            # Root simulation folder
            root_simulation_dir = output_path
            os.makedirs(root_simulation_dir, exist_ok=True)
            
            # Create _input_files folder and copy all data files there
            data_files_folder = os.path.join(root_simulation_dir, "_input_files")
            os.makedirs(data_files_folder, exist_ok=True)
            
            # Generate base settings file
            base_settings_result = self.generate_base_settings_file(root_simulation_dir)
            if not base_settings_result["success"]:
                return base_settings_result
            
            # Copy all data files to _input_files
            data_file_dest_paths = {}
            for i, system_file in enumerate(system_files):
                system_name = Path(system_file).stem
                data_file_dest = os.path.join(data_files_folder, f"{system_name}.data")
                
                # Process the data file to remove Pair Coeffs section if it exists
                self.process_and_copy_data_file(system_file, data_file_dest)
                
                data_file_dest_paths[system_file] = (Path("_input_files") / f"{system_name}.data").as_posix()
                
                # Copy potential file if used (potential files are not processed)
                system_config = self.config.get("system", {})
                if system_config.get("use_potential_file", False):
                    potential_file = system_config.get("potential_file", "")
                    if os.path.exists(potential_file):
                        potential_dest = os.path.join(data_files_folder, Path(potential_file).name)
                        shutil.copy2(potential_file, potential_dest)
            
            # Get deformation studies
            deform_studies = self.config.get("multistudy", {}).get("deform_studies", [])
            if not deform_studies:
                return {"success": False, "message": "No deformation studies defined."}
            
            # Generate scripts for each deformation study and system combination
            for study in deform_studies:
                study_name = study.get("name", "study")
                
                # Create deformation study folder
                study_folder = os.path.join(root_simulation_dir, study_name)
                os.makedirs(study_folder, exist_ok=True)
                
                for system_file in system_files:
                    system_name = Path(system_file).stem
                    
                    # Always create system-specific folder within study folder for consistent structure
                    system_folder = os.path.join(study_folder, system_name)
                    os.makedirs(system_folder, exist_ok=True)
                    
                    # Generate script for this study-system combination
                    model_name = f"{study_name}_{system_name}"
                    data_file_relative_path = data_file_dest_paths[system_file]
                    
                    result = self.generate_single_script(
                        system_file, model_name, study, 
                        system_folder, data_file_relative_path
                    )
                    
                    if not result["success"]:
                        return result
            
            # Always generate both local and cluster execution scripts
            exec_script_result = self.generate_execution_script(root_simulation_dir, system_files, deform_studies, is_multi_system)
            if not exec_script_result["success"]:
                return exec_script_result
            
            cluster_script_result = self.generate_cluster_submission_script(root_simulation_dir, system_files, deform_studies, is_multi_system)
            if not cluster_script_result["success"]:
                return cluster_script_result
            
            # Save settings to JSON file
            settings_result = self.save_settings_to_json(root_simulation_dir)
            if not settings_result["success"]:
                return settings_result
            
            return {"success": True, "message": "All scripts generated successfully.", "files": self.generated_files}
            
        except Exception as e:
            return {"success": False, "message": f"Error generating scripts: {str(e)}"}
        
    def process_and_copy_data_file(self, source_path, dest_path):
        """
        Process and copy a data file, removing the 'Pair Coeffs' section if present.
        
        This function copies a LAMMPS data file from source to destination, but removes
        the 'Pair Coeffs' section if it exists to avoid the error:
        ERROR: Must define pair_style before Pair Coeffs (src/read_data.cpp:686)
        """
        with open(source_path, 'r') as infile:
            lines = infile.readlines()
        
        # Process lines to remove Pair Coeffs section if it exists
        processed_lines = []
        in_pair_coeffs_section = False
        current_line_index = 0
        
        while current_line_index < len(lines):
            line = lines[current_line_index]
            line_stripped = line.strip()
            
            if line_stripped.startswith("Pair Coeffs"):
                # Found the start of the Pair Coeffs section, skip it
                in_pair_coeffs_section = True
                current_line_index += 1
                continue
            
            # Check if we are in the Pair Coeffs section and if this line starts with a letter
            if in_pair_coeffs_section:
                # Check if the line starts with a letter (non-whitespace character)
                line_stripped_no_ws = line.lstrip()  # Remove leading whitespace
                if line_stripped_no_ws and line_stripped_no_ws[0].isalpha():
                    # This is the start of the next section, so we're done skipping
                    in_pair_coeffs_section = False
                    # Add this line to the output as it's the start of the next section
                    processed_lines.append(lines[current_line_index])
                # Skip all lines while in_pair_coeffs_section is True
            else:
                # We're not in the Pair Coeffs section, so add the line to output
                processed_lines.append(lines[current_line_index])
            
            current_line_index += 1
        
        # Write the processed content to the destination
        with open(dest_path, 'w') as outfile:
            outfile.writelines(processed_lines)

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
        """Check if all data files have the same units"""
        if not system_files:
            return {"consistent": True, "units": None}
        first_units = self.read_units_from_data_file(system_files[0])
        for file_path in system_files[1:]:
            units = self.read_units_from_data_file(file_path)
            if units != first_units:
                return {"consistent": False, "message": f"Units mismatch: {file_path} has '{units}', but first file has '{first_units}'"}
        return {"consistent": True, "units": first_units}
        
    def generate_single_script(self, data_file, model_name, deform_study, output_dir, data_file_dest):
        """Generate a single LAMMPS input script"""
        try:
            script_filename = os.path.join(output_dir, f"{model_name}.in")
            script_content = self.generate_script_content(data_file_dest, model_name, deform_study)
            with open(script_filename, 'w') as f:
                f.write(script_content)
            self.generated_files.append(script_filename)
            return {"success": True, "message": f"Script generated: {script_filename}", "script_file": script_filename}
        except Exception as e:
            return {"success": False, "message": f"Error generating script: {str(e)}"}

    def generate_script_content(self, data_file, model_name, deform_study):
        """Generate the content of a LAMMPS input script"""
        try:
            system_config = self.config.get("system", {})
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

            if enable_restart:
                script_lines.extend([
                    "#------------------------", "# Restart Setup", "#------------------------",
                    "shell \"mkdir -p restart_files\"",
                    f"if \"${{curstep}} > 0\" then \"read_restart restart_files/{model_name}.restart.${{curstep}}\" &",
                    f"else \"read_data ../../{data_file}\"", ""
                ])
            else:
                script_lines.extend(["#------------------------", "# System Setup", "#------------------------", f"read_data ../../{data_file}", ""])

            if system_config.get("use_potential_file", False):
                potential_file = system_config.get("potential_file", "")
                if potential_file:
                    potential_path = (Path("_input_files") / Path(potential_file).name).as_posix()
                    script_lines.extend([f"include ../../{potential_path}", ""])

            deform_axis = deform_study.get("deform_axis", "x")
            mode = deform_study.get("mode", "Deformation")
            is_shear = deform_axis in ["xy", "xz", "yz"]
            ensemble_config = deform_study.get("ensemble", {})
            if (ensemble_config.get("ensemble") == "NPT" and ensemble_config.get("npt_aniso") == "tri") or is_shear:
                script_lines.extend(["change_box all triclinic", ""])

            points = deform_study.get("data_points", [])

            if mode == "Temperature":
                script_lines.extend(["#------------------------", "# Temperature Variables", "#------------------------"])
                initial_temp = points[0][1] if points else 300.0
                script_lines.extend([f"variable set_temp equal {initial_temp}", ""])

            fixes_computes_lines, final_thermo_style = self._generate_fixes_computes_section(deform_study, output_config, fixes_config, mode, deform_axis, is_shear)
            if fixes_computes_lines:
                script_lines.extend(["#------------------------", "# Fixes & Computes", "#------------------------", *fixes_computes_lines])
            
            if system_config.get("enable_velocity", True):
                initial_temp = points[0][1] if mode == "Temperature" and points else ensemble_config.get("temperature", 300.0)
                velocity_command = f"velocity all create {initial_temp} {system_config.get('initial_velocity_seed', 12345)} mom yes rot yes dist gaussian"
                
                if enable_restart:
                    script_lines.extend([
                        "#------------------------", "# Initial Velocity", "#------------------------",
                        f"if \"${{curstep}} == 0\" then \"{velocity_command}\"",
                        ""
                    ])
                else:
                    script_lines.extend([
                        "#------------------------", "# Initial Velocity", "#------------------------",
                        velocity_command,
                        ""
                    ])

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
                    if block: script_lines.append(f"if \"${{curstep}} == {step}\" then \"jump SELF segment_{block['user_segment_id']}_{step}\"")

                if max_steps > 0:
                    script_lines.append(f"if \"${{curstep}} == {int(max_steps)}\" then \"jump SELF end\"")
                
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
                        
                        amp = segment_info.get('amplitude_strain', 0)
                        period = segment_info.get('period_steps', 0)
                        phase = segment_info.get('phase_shift_steps', 0)
                        ashift = segment_info.get('ashift_factor', 0)
                        
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
        
        segment_info = block_info.get("segment_info", {'type': 'line'})

        lines.append(f"\n# --- Segment {block_info['user_segment_id']}: from step {start_step} to {end_step} ---")
        lines.append(f"label segment_{block_info['user_segment_id']}_{start_step}")

        if has_sine_segment and segment_info.get('type') == 'line':
            lines.append("variable started equal 0")

        if segment_info.get('type') == 'sine' and mode == "Deformation":
            lines.append(f"if \"$(v_started) == 1\" then \"jump SELF segment_{block_info['user_segment_id']}_init\"")
            lines.append(f"variable sinState equal $(v_A * sin(2*PI * (step-v_phaseShift)/v_Sp) + v_Ashift)")
            lines.append(f"fix deform all deform 1 {deform_axis} variable v_displace v_rate units box remap x flip no")

        elif mode == "Deformation": # This is now the 'line' segment case
            sub_start_y, sub_end_y = block_info['sub_start_y'], block_info['sub_end_y']
            final_target_y = sub_end_y
            if is_shear:
                lines.append(f"variable tilt_target equal \"{final_target_y} * v_L0{deform_axis[1]}\"")
                lines.append(f"fix deform all deform 1 {deform_axis} final ${{tilt_target}} units box remap x flip no")
            else:
                deform_scenario = deform_study.get("deform_scenario", "symmetric")
                if deform_scenario == "shift hi, fix lo":
                    lines.extend([f'variable {deform_axis}lo_target equal v_{deform_axis}lo0', f'variable {deform_axis}hi_target equal "v_{deform_axis}hi0 + (v_L0{deform_axis} * {final_target_y})"'])
                elif deform_scenario == "shift lo, fix hi":
                    lines.extend([f'variable {deform_axis}lo_target equal "v_{deform_axis}lo0 - (v_L0{deform_axis} * {final_target_y})"', f"variable {deform_axis}hi_target equal v_{deform_axis}hi0"])
                else: # symmetric
                    lines.extend([f'variable {deform_axis}lo_target equal "v_{deform_axis}lo0 - (v_L0{deform_axis} * {final_target_y}) / 2"', f'variable {deform_axis}hi_target equal "v_{deform_axis}hi0 + (v_L0{deform_axis} * {final_target_y}) / 2"'])
                lines.append(f"fix deform all deform 1 {deform_axis} final ${{{deform_axis}lo_target}} ${{{deform_axis}hi_target}} units box remap x flip no")
        
        elif mode == "Temperature":
            sub_start_y, sub_end_y = block_info['sub_start_y'], block_info['sub_end_y']
            slope = (sub_end_y - sub_start_y) / duration if duration > 0 else 0
            lines.extend([f"variable ramp_slope equal {slope}", f"variable set_temp equal \"{sub_start_y} + (step - {start_step}) * v_ramp_slope\""])

        temp = ensemble_config.get("temperature", 300.0)
        pressure = ensemble_config.get("pressure", 1.0)
        damping = system_config.get("damping_factor", 100.0)
        
        temp_start_ens, temp_end_ens = (block_info.get('sub_start_y', temp), block_info.get('sub_end_y', temp)) if mode == "Temperature" else (temp, temp)
        
        if ensemble == "NVT":
            lines.append(f"fix ensemble all nvt temp {temp_start_ens} {temp_end_ens} $({damping}*dt)")
        elif ensemble == "NPT":
            npt_aniso = ensemble_config.get("npt_aniso", "iso")
            lines.append(f"fix ensemble all npt temp {temp_start_ens} {temp_end_ens} $({damping}*dt) {npt_aniso} {pressure} {pressure} $(1000*dt)")

        lines.append(f"run {int(duration)}")
        
        if mode == "Deformation": lines.append("unfix deform")
        lines.append("unfix ensemble")
        
        return lines

    def _generate_fixes_computes_section(self, deform_study, output_config, fixes_config, mode, deform_axis, is_shear):
        """Generates the full string for the Fixes & Computes section, including time-averaging."""
        lines = []
        
        base_thermo_style = output_config.get("thermo_style", "step ...")
        thermo_style_parts = base_thermo_style.split()

        # --- Define all possible strain/stress variables if in Deformation mode ---
        if mode == "Deformation":
            lines.extend([
                "# Engineering Strain & Cauchy Stress Variables",
                "variable L0x equal $(lx)",
                "variable L0y equal $(ly)",
                "variable L0z equal $(lz)",
                "variable xlo0 equal $(xlo)",
                "variable xhi0 equal $(xhi)",
                "variable ylo0 equal $(ylo)",
                "variable yhi0 equal $(yhi)",
                "variable zlo0 equal $(zlo)",
                "variable zhi0 equal $(zhi)",
                "variable exx equal (lx-v_L0x)/v_L0x",
                "variable eyy equal (ly-v_L0y)/v_L0y",
                "variable ezz equal (lz-v_L0z)/v_L0z",
                "variable exy equal xy/v_L0y",
                "variable exz equal xz/v_L0z",
                "variable eyz equal yz/v_L0z",
                "variable cauchy_xx equal -pxx",
                "variable cauchy_yy equal -pyy",
                "variable cauchy_zz equal -pzz",
                "variable cauchy_xy equal -pxy",
                "variable cauchy_xz equal -pxz",
                "variable cauchy_yz equal -pyz",
                "variable hydrostatic equal (v_cauchy_xx+v_cauchy_yy+v_cauchy_zz)/3",
                'variable vMises equal "sqrt(0.5*((v_cauchy_xx-v_cauchy_yy)^2+(v_cauchy_yy-v_cauchy_zz)^2+(v_cauchy_zz-v_cauchy_xx)^2+6*(v_cauchy_xy^2+v_cauchy_yz^2+v_cauchy_xz^2)))"',
                ""
            ])

        # --- Add selected strains/stresses to thermo output ---
        if mode == "Deformation":
            strain_map = {'εxx': 'exx', 'εyy': 'eyy', 'εzz': 'ezz', 'εxy': 'exy', 'εxz': 'exz', 'εyz': 'eyz'}
            for strain in output_config.get("eng_strains", []):
                if strain == 'deformation direction':
                    axis_suffix = deform_axis if is_shear else deform_axis * 2
                    thermo_style_parts.append(f"v_e{axis_suffix}")
                elif strain in strain_map:
                    thermo_style_parts.append(f"v_{strain_map[strain]}")
            
            stress_map = {'σxx': 'cauchy_xx', 'σyy': 'cauchy_yy', 'σzz': 'cauchy_zz', 'σxy': 'cauchy_xy', 'σxz': 'cauchy_xz', 'σyz': 'cauchy_yz', 'von Mises': 'vMises', 'hydrostatic': 'hydrostatic'}
            for stress in output_config.get("cauchy_stresses", []):
                if stress == 'deformation direction':
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
            lines.append("# --- Time Averaging Computes ---")
            processed_vars = set() # Keep track of variables we've already processed

            pressure_terms = {'press', 'pxx', 'pyy', 'pzz', 'pxy', 'pxz', 'pyz'}
            if any(term in averaged_quantities for term in pressure_terms):
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
                if 'press' in averaged_quantities: thermo_style_parts.append("v_press_avg")
                if 'pxx' in averaged_quantities: thermo_style_parts.append("v_pxx_avg")
                if 'pyy' in averaged_quantities: thermo_style_parts.append("v_pyy_avg")
                if 'pzz' in averaged_quantities: thermo_style_parts.append("v_pzz_avg")
                if 'pxy' in averaged_quantities: thermo_style_parts.append("v_pxy_avg")
                if 'pxz' in averaged_quantities: thermo_style_parts.append("v_pxz_avg")
                if 'pyz' in averaged_quantities: thermo_style_parts.append("v_pyz_avg")

            if 'temp' in averaged_quantities:
                lines.append("compute avg_temp_compute all temp")
                lines.append(f"fix avg_temp all ave/time {nevery} {nrepeat} {nfreq} c_avg_temp_compute")
                lines.append("variable temp_avg equal f_avg_temp")
                thermo_style_parts.append("v_temp_avg")
            if 'ke' in averaged_quantities:
                lines.append("compute avg_ke_total_compute all reduce sum ke")
                lines.append(f"fix avg_ke all ave/time {nevery} {nrepeat} {nfreq} c_avg_ke_total_compute")
                lines.append("variable ke_avg equal f_avg_ke")
                thermo_style_parts.append("v_ke_avg")
            if 'pe' in averaged_quantities:
                lines.append("compute avg_pe_total_compute all reduce sum pe")
                lines.append(f"fix avg_pe all ave/time {nevery} {nrepeat} {nfreq} c_avg_pe_total_compute")
                lines.append("variable pe_avg equal f_avg_pe")
                thermo_style_parts.append("v_pe_avg")
            
            # Averaging for selected strains and stresses
            if 'strain' in averaged_quantities and mode == "Deformation":
                for strain in output_config.get("eng_strains", []):
                    var_name = None
                    if strain == 'deformation direction':
                        axis_suffix = deform_axis if is_shear else deform_axis * 2
                        var_name = f"e{axis_suffix}"
                    elif strain in strain_map:
                        var_name = strain_map[strain]
                    
                    if var_name and var_name not in processed_vars:
                        lines.append(f"fix avg_{var_name} all ave/time {nevery} {nrepeat} {nfreq} v_{var_name}")
                        lines.append(f"variable {var_name}_avg equal f_avg_{var_name}")
                        thermo_style_parts.append(f"v_{var_name}_avg")
                        processed_vars.add(var_name)
            
            if 'stress' in averaged_quantities and mode == "Deformation":
                for stress in output_config.get("cauchy_stresses", []):
                    var_name = None
                    if stress == 'deformation direction':
                        axis_suffix = deform_axis if is_shear else deform_axis * 2
                        var_name = f"cauchy_{axis_suffix}"
                    elif stress in stress_map:
                        var_name = stress_map[stress]

                    if var_name and var_name not in processed_vars:
                        lines.append(f"fix avg_{var_name} all ave/time {nevery} {nrepeat} {nfreq} v_{var_name}")
                        lines.append(f"variable {var_name}_avg equal f_avg_{var_name}")
                        thermo_style_parts.append(f"v_{var_name}_avg")
                        processed_vars.add(var_name)
            
            lines.append("")

        # --- Custom Fixes/Computes ---
        if fixes_config.get("enable_custom_fixes", False):
            custom_fixes = fixes_config.get("custom_fixes", "")
            if custom_fixes:
                lines.extend(["# Custom Fixes", custom_fixes, ""])
        if output_config.get("enable_custom_computes", False):
            custom_computes = output_config.get("custom_computes", "")
            if custom_computes:
                lines.extend(["# Custom Computes", custom_computes, ""])

        final_thermo_style = " ".join(dict.fromkeys(thermo_style_parts))
        
        return lines, final_thermo_style

    def _generate_bond_breakage_section(self, config):
        lines = ["#------------------------", "# Bond Breakage", "#------------------------"]
        nevery = config.get("nevery", 1)
        bondtype = config.get("bondtype", 1)
        rmax = config.get("rmax", 1.5)
        cmd = f"fix break_bonds all bond/break {nevery} {bondtype} {rmax}"
        if config.get("enable_prob", False):
            cmd += f" prob {config.get('prob_fraction', 0.1)} {config.get('prob_seed', 12345)}"
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
                f"dump trajectory all custom {config.get('traj_freq', 100)} {model_name}.{config.get('traj_format', 'lammpstrj')} {config.get('trj_output_items', 'id type x y z')}", ""
            ])
        if config.get("custom_dumps", ""):
            lines.extend(["# Custom Dumps", config.get("custom_dumps", ""), ""])
        return lines
        
    def generate_execution_script(self, root_simulation_dir, system_files, deform_studies, is_multi_system):
        """Generate execution script for local, multi-terminal processing."""
        try:
            import platform
            current_os = platform.system().lower()
            
            job_config = self.config.get("job_submission", {})
            
            # --- Define OS-specific commands and script structure ---
            if current_os in ['linux', 'darwin']:  # Linux or Mac
                exec_path = os.path.join(root_simulation_dir, "local_run_all.sh")
                lines = [
                    "#!/bin/bash",
                    "# Execution script to run each LAMMPS simulation in a new terminal.",
                    "# For Linux/Mac systems.", "",
                    "echo 'Starting LAMMPS simulations in new terminals...'", ""
                ]
                # This command opens a new terminal, executes the lammps command, and keeps the terminal open
                command_prefix = "gnome-terminal -- bash -c '"
                command_suffix = "; exec bash'"
            else:  # Windows
                exec_path = os.path.join(root_simulation_dir, "local_run_all.bat")
                lines = [
                    "@echo off",
                    "REM Execution script to run each LAMMPS simulation in a new command prompt.",
                    "REM For Windows systems.", "",
                    "echo Starting LAMMPS simulations in new command prompts...", ""
                ]
                # This command opens a new command prompt that remains open after the command finishes
                command_prefix = "start cmd /k "
                command_suffix = ""

            # --- Construct the base LAMMPS command for local execution ---
            local_lammps_cmd = job_config.get("local_lammps_cmd", "lmp")
            if job_config.get("local_multiprocessor", False):
                lammps_executable = job_config.get("local_lammps_executable", "lmp_mpi")
                num_processors = job_config.get("local_processors", 1)
                full_local_cmd = f"{local_lammps_cmd} -np {num_processors} {lammps_executable}"
            else:
                full_local_cmd = local_lammps_cmd

            # Add log file and variables for local runs to prevent script errors.
            # curstep is always 0 for a fresh local run. maxtime is a huge number.
            log_file = job_config.get("log_file_name", "job.log")
            full_local_cmd += f" -log {log_file} -var curstep 0 -var maxtime 1e99"

            # --- Loop through studies and generate commands ---
            for study in deform_studies:
                study_name = study.get("name", "study")
                for system_file in system_files:
                    system_name = Path(system_file).stem
                    model_name = f"{study_name}_{system_name}"
                    sim_directory = f"{study_name}/{system_name}"
                    
                    # This structure matches the old, working version
                    lines.extend([
                        f"echo 'Running simulation: {model_name}'",
                        f"cd {sim_directory}",
                        f"{command_prefix}{full_local_cmd} -in {model_name}.in{command_suffix}",
                        f"echo 'Started simulation in new terminal: {model_name}'",
                        f"cd ../../",
                        ""
                    ])

            # --- Add final messages ---
            if current_os in ['linux', 'darwin']:
                lines.extend(["echo 'All simulation terminals started.'", "echo 'Each simulation runs in its own terminal window.'", ""])
            else:
                lines.extend(["echo All simulation terminals started.", "echo Each simulation runs in its own command prompt window.", ""])
            
            # --- Write the script file ---
            with open(exec_path, 'w', newline='\n') as f:
                f.write("\n".join(lines))
            
            if current_os in ['linux', 'darwin']:
                os.chmod(exec_path, 0o755)
            
            self.generated_files.append(exec_path)
            return {"success": True, "message": f"Execution script generated: {exec_path}"}
            
        except Exception as e:
            return {"success": False, "message": f"Error generating execution script: {str(e)}"}

    def generate_cluster_submission_script(self, root_simulation_dir, system_files, deform_studies, is_multi_system):
        """Generate single master cluster job file and submission script"""
        try:
            job_config = self.config.get("job_submission", {})
            enable_restart = job_config.get("enable_restart", False)

            # Master Job File (lammps_simulation.job)
            master_job_path = os.path.join(root_simulation_dir, "lammps_simulation.job")
            job_lines = [job_config.get("slurm_header", "#!/bin/bash\n#SBATCH --time=24:00:00"), ""]
            
            if enable_restart:
                hours = job_config.get("runtime_threshold_hours", 23)
                mins = job_config.get("runtime_threshold_minutes", 45)
                maxtime = hours * 3600 + mins * 60
                delete_restarts = "true" if job_config.get("delete_restart_files", False) else "false"

                job_lines.extend([
                    "input_file=$1",
                    "if [ -z \"$input_file\" ]; then echo 'Error: No input file specified'; exit 1; fi",
                    "MODEL_NAME=$(basename \"$input_file\" .in)",
                    "SIM_DIR=$(dirname \"$input_file\")",
                    "cd \"$SIM_DIR\"",
                    "",
                    "# --- Restart Logic ---",
                    "curstep=0",
                    "if [ -d restart_files ] && [ \"$(ls -A restart_files)\" ]; then",
                    "  latest_restart=$(ls -v restart_files/${MODEL_NAME}.restart.* | tail -n 1)",
                    "  if [ -n \"$latest_restart\" ]; then",
                    "    curstep=$(basename \"$latest_restart\" | sed 's/.*\\.//')",
                    "    echo \"Found latest restart file with step: $curstep\"",
                    "  fi",
                    "fi",
                    "",
                    "# --- Run LAMMPS ---",
                    f"module load {job_config.get('module_load', 'lammps')}",
                    f"{job_config.get('srun_cmd', 'srun')} {job_config.get('cluster_lammps_cmd', 'lmp')} -in \"$input_file\" -log none -var curstep $curstep -var maxtime {maxtime}",
                    "",
                    "# --- Post-Run Resubmission and Cleanup (on Rank 0 only to prevent job stampede) ---",
                    "if [ \"${SLURM_PROCID:-0}\" -eq 0 ]; then",
                    "    if [ -f resubmit.flag ]; then",
                    "        echo \"Resubmit flag found. Resubmitting for next segment.\"",
                    "        rm resubmit.flag",
                    f"        {job_config.get('sbatch_cmd', 'sbatch')} --job-name=\"$SLURM_JOB_NAME\" --mail-type=ALL \"../../lammps_simulation.job\" \"$input_file\"",
                    "    elif [ -f finished.flag ]; then",
                    "        echo \"Simulation completed successfully.\"",
                    f"        if [ \"{delete_restarts}\" = \"true\" ]; then",
                    "            echo \"Cleanup is enabled. Deleting restart_files directory.\"",
                    "            rm -rf restart_files",
                    "        fi",
                    "        rm finished.flag",
                    "    else",
                    "        echo \"No resubmit or finished flag found. Assuming failure. No resubmission or cleanup.\"",
                    "    fi",
                    "    echo \"Job script for ${MODEL_NAME} finished.\"",
                    "fi"
                ])
            else: # Simple, no-restart version
                job_lines.extend([
                    "input_file=$1",
                    "SIM_DIR=$(dirname \"$input_file\")",
                    f"module load {job_config.get('module_load', 'lammps')}",
                    f"cd \"$SIM_DIR\"",
                    f"{job_config.get('srun_cmd', 'srun')} {job_config.get('cluster_lammps_cmd', 'lmp')} -in \"$input_file\"",
                    "echo \"Simulation Completed.\""
                ])
            
            with open(master_job_path, 'w', newline='\n') as f: f.write("\n".join(job_lines))
            os.chmod(master_job_path, 0o755)
            self.generated_files.append(master_job_path)

            # Submission Script (cluster_run_jobs.sh)
            cluster_script_path = os.path.join(root_simulation_dir, "cluster_run_jobs.sh")
            script_lines = ["#!/bin/bash", "# Submits all simulation jobs to the cluster.", ""]
            
            for study in deform_studies:
                for system_file in system_files:
                    sys_name = Path(system_file).stem
                    model_name = f"{study['name']}_{sys_name}"
                    sim_directory = f"{study['name']}/{sys_name}"
                    input_file_name = f"{model_name}.in"
                    
                    script_lines.append(f"cd {sim_directory}")
                    script_lines.append(f"{job_config.get('sbatch_cmd', 'sbatch')} --job-name=\"{model_name}\" --mail-type=ALL \"../../lammps_simulation.job\" \"{input_file_name}\"")
                    script_lines.append("cd ../../")
                    script_lines.append("")

            total_jobs = len(deform_studies) * len(system_files)
            num_studies = len(deform_studies)
            num_systems = len(system_files)

            if total_jobs == 1:
                final_message = "echo '1 cluster job submitted. Use squeue to monitor the job status.'"
            else:
                study_word = "study" if num_studies == 1 else "studies"
                system_word = "system" if num_systems == 1 else "systems"
                each_phrase = " each" if num_studies > 1 else ""
                final_message = f"echo 'All {total_jobs} cluster jobs submitted: {num_studies} {study_word} with {num_systems} {system_word}{each_phrase}. Use squeue to monitor the job status.'"
            
            script_lines.append(final_message)
            
            with open(cluster_script_path, 'w', newline='\n') as f: f.write("\n".join(script_lines))
            os.chmod(cluster_script_path, 0o755)
            self.generated_files.append(cluster_script_path)

            return {"success": True, "message": f"Master job file and submission script generated."}
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
                f"boundary {config.get('boundary_x', 'p')} {config.get('boundary_y', 'p')} {config.get('boundary_z', 'p')}",
                "", "# Ensemble Settings", f"timestep {config.get('timestep', 0.001)}",
                "", "# Neighbor Settings",
            ]
            if config.get('enable_neighbor_distance', True):
                lines.append(f"neighbor {config.get('neighbor_distance', 0.3)} bin")
            
            neigh_modify_parts = ["neigh_modify"]
            if config.get('enable_neigh_modify_every', True): neigh_modify_parts.append(f"every {config.get('neigh_modify_every', 1)}")
            if config.get('enable_neigh_modify_delay', True): neigh_modify_parts.append(f"delay {config.get('neigh_modify_delay', 10)}")
            if config.get('enable_neigh_modify_check', True): neigh_modify_parts.append(f"check {config.get('neigh_modify_check', 'yes')}")
            if config.get('enable_neigh_modify_one', False): neigh_modify_parts.append(f"one {config.get('neigh_modify_one', 0)}")
            
            if len(neigh_modify_parts) > 1:
                lines.append(" ".join(neigh_modify_parts))

            base_settings_file = os.path.join(root_simulation_dir, "base_input.in")
            with open(base_settings_file, 'w') as f: f.write("\n".join(lines))
            self.generated_files.append(base_settings_file)
            return {"success": True}
        except Exception as e:
            return {"success": False, "message": f"Error generating base settings file: {str(e)}"}
        
    def read_units_from_data_file(self, data_file):
        """Read units from the first line of a LAMMPS data file."""
        try:
            with open(data_file, 'r') as f:
                first_line = f.readline().strip()
                if "units" in first_line:
                    return first_line.split("units")[-1].strip().split()[0]
        except Exception:
            pass
        return "metal" # Default