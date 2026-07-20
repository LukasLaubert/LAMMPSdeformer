#!/usr/bin/env python3
"""
LAMMPS Script Generator - Redesigned Version

Handles the generation of LAMMPS input scripts and cluster job files
based on user configuration with support for symmetric wall movement,
engineering strain, proper units handling, and structured file generation.
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
                system_files = glob.glob(os.path.join(system_path, "*.data"))
                is_multi_system = len(system_files) > 1
                if not system_files:
                    return {"success": False, "message": "No .data files found in the specified directory."}
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
                    model_name = f"{study_name}_{system_name}"  # Changed to study_name_first
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
            
            # Create a copy of the config to avoid modifying the original
            settings_to_save = self.config.copy()
            
            # Remove any sensitive or temporary data if needed
            if "system" in settings_to_save and "system_path" in settings_to_save["system"]:
                # Keep the system path as it's needed for restoration
                pass
            
            # Write settings to JSON file
            with open(settings_file, 'w') as f:
                json.dump(settings_to_save, f, indent=2)
            
            self.generated_files.append(settings_file)
            
            return {"success": True, "message": f"Settings saved to: {settings_file}"}
            
        except Exception as e:
            return {"success": False, "message": f"Error saving settings: {str(e)}"}
        
    def check_units_consistency(self, system_files):
        """Check if all data files have the same units"""
        if not system_files:
            return {"consistent": True, "units": None}
            
        # Read units from the first file
        first_units = self.read_units_from_data_file(system_files[0])
        
        # Check units in all other files
        for file_path in system_files[1:]:
            units = self.read_units_from_data_file(file_path)
            if units != first_units:
                return {
                    "consistent": False, 
                    "units": None,
                    "message": f"Units mismatch: {file_path} has units '{units}' but first file has units '{first_units}'"
                }
                
        return {"consistent": True, "units": first_units}
        
    def generate_single_script(self, data_file, model_name, deform_study, output_dir, data_file_dest):
        """Generate a single LAMMPS input script"""
        try:
            # Generate script filename
            script_filename = os.path.join(output_dir, f"{model_name}.in")
            
            # Generate the script content
            script_content = self.generate_script_content(data_file_dest, model_name, deform_study)
            
            # Write the script to file
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
            output_config = self.config.get("output", {})
            
            script_lines = [
                f"# {model_name}.in",
                f"# Generated by LAMMPS Input Script Generator on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                ""
            ]
            
            # Include the base settings
            script_lines.extend([
                "#------------------------",
                "# Base settings",
                "#------------------------",
                "include ../../base_input.in",
                ""
            ])
            
            # For restart functionality, we need to conditionally read either restart or data files
            job_submission_config = self.config.get("job_submission", {})
            enable_restart = job_submission_config.get("enable_restart", False)
            
            # Add start settings if restart is enabled (before data/potential)
            if enable_restart:
                restart_freq = job_submission_config.get("restart_freq", 1000)
                halt_freq = job_submission_config.get("halt_freq", 100)  # Default to 100
                max_time_buffer = job_submission_config.get("max_time_buffer", 600)  # Default 10 minutes
                
                # Create restart_files directory and add start settings
                script_lines.extend([
                    "#------------------------",
                    "# Start settings",
                    "#------------------------",
                    "# Create directory for restart files",
                    "shell \"mkdir restart_files\"",
                    f"restart {restart_freq} restart_files/{model_name}.restart.*",
                    ""
                ])
                
                # Add conditional read commands (replacing the read_data command)
                script_lines.extend([
                    "# Conditional read based on restart flag",
                    f"if \"${{restart}}==TRUE\" then &",
                    f"    \"read_restart restart_files/{model_name}.restart\" &",
                    f"else &",
                    f"    \"read_data ../../{data_file}\"",
                    ""
                ])
                
                # Add potential file include after the conditional logic if needed
                if system_config.get("use_potential_file", False):
                    potential_file = system_config.get("potential_file", "")
                    if potential_file:
                        potential_name = Path(potential_file).name
                        potential_path = (Path("_input_files") / potential_name).as_posix()
                        script_lines.extend([
                            f"include ../../{potential_path}",
                            ""
                        ])
                
                # Add the halt check command after the potential file is included
                # This ensures it's not started before the simulation box is loaded
                script_lines.extend([
                    "# Halt check: stop simulation before walltime limit to allow for restart",
                    "# The maxtime variable will be passed from the job script when running with -var maxtime",
                    f"fix stop_early all halt {halt_freq} tlimit > ${{maxtime}}",
                    ""
                ])
                
                # Add triclinic box setting if NPT aniso is set to "tri"
                ensemble_config = deform_study.get("ensemble", {})
                ensemble = ensemble_config.get("ensemble", "NVT")
                npt_aniso = ensemble_config.get("npt_aniso", "iso")  # Get the new anisotropic setting
                if ensemble == "NPT" and npt_aniso == "tri":
                    script_lines.extend([
                        "# Triclinic boundaries are required for NPT anisotropic simulation with 'tri' setting",
                        "change_box all triclinic",
                        ""
                    ])
            else:
                # For non-restart case, read data and potential directly
                script_lines.extend([
                    "#------------------------",
                    "# Read data and set (optional) potentials",
                    "#------------------------",
                    f"read_data ../../{data_file}"
                ])
                
                if system_config.get("use_potential_file", False):
                    potential_file = system_config.get("potential_file", "")
                    if potential_file:
                        potential_name = Path(potential_file).name
                        potential_path = (Path("_input_files") / potential_name).as_posix()
                        script_lines.append(f"include ../../{potential_path}")
                script_lines.append("")
                
                # Add triclinic box setting if NPT aniso is set to "tri"
                ensemble_config = deform_study.get("ensemble", {})
                ensemble = ensemble_config.get("ensemble", "NVT")
                npt_aniso = ensemble_config.get("npt_aniso", "iso")  # Get the new anisotropic setting
                if ensemble == "NPT" and npt_aniso == "tri":
                    script_lines.extend([
                        "# Triclinic boundaries are required for NPT anisotropic simulation with 'tri' setting",
                        "change_box all triclinic",
                        ""
                    ])

            # Variables
            deform_axis = deform_study.get("deform_axis", "x")
            script_lines.extend([
                "#------------------------",
                "# Variables",
                "#------------------------",
                f"variable L0{deform_axis} equal $(l{deform_axis})",
                f"variable {deform_axis}lo0 equal $({deform_axis}lo)",
                f"variable {deform_axis}hi0 equal $({deform_axis}hi)",
                f"variable estrain_{deform_axis}{deform_axis} equal (l{deform_axis}-v_L0{deform_axis})/v_L0{deform_axis}",
                f""
                ""
            ])

            # Fixes & Computes section
            fixes_computes_lines = []
            
            thermo_style = output_config.get("thermo_style", "step etotal pe ke epair ebond evdwl ecoul elong temp press pxx pyy pzz pxy pxz pyz lx ly lz density")
            averaged_quantities = output_config.get("averaged_quantities", [])
            avg_nevery = output_config.get("avg_nevery", 1)
            thermo_output_freq = output_config.get("thermo_freq", 100)
            mode = deform_study.get("mode", "Deformation")
            deform_axis = deform_study.get("deform_axis", "x")

            if averaged_quantities:
                nevery = avg_nevery
                if nevery <= 0: nevery = 1
                nfreq = thermo_output_freq
                if nfreq < nevery: nfreq = nevery
                nrepeat = nfreq // nevery

                computes_defined = set()
                thermo_avg_keywords = []
                
                pressure_map = {
                    'pxx': 1, 'pyy': 2, 'pzz': 3,
                    'pxy': 4, 'pxz': 5, 'pyz': 6
                }

                for qty in averaged_quantities:
                    if qty == 'temp':
                        if 'temp' not in computes_defined:
                            fixes_computes_lines.append("compute avg_temp_compute all temp")
                            computes_defined.add('temp')
                        fixes_computes_lines.append(f"fix avg_temp all ave/time {nevery} {nrepeat} {nfreq} c_avg_temp_compute")
                        fixes_computes_lines.append("variable temp_avg equal f_avg_temp")
                        thermo_avg_keywords.append("v_temp_avg")
                    
                    elif qty in pressure_map or qty == 'press':
                        if 'pressure' not in computes_defined:
                            fixes_computes_lines.append("compute avg_press_compute all pressure thermo_temp")
                            computes_defined.add('pressure')
                        
                        if qty == 'press':
                            fixes_computes_lines.append(f"fix avg_press all ave/time {nevery} {nrepeat} {nfreq} c_avg_press_compute")
                            fixes_computes_lines.append("variable press_avg equal f_avg_press")
                            thermo_avg_keywords.append("v_press_avg")
                        else:
                            index = pressure_map[qty]
                            fixes_computes_lines.append(f"fix avg_{qty} all ave/time {nevery} {nrepeat} {nfreq} c_avg_press_compute[{index}]")
                            fixes_computes_lines.append(f"variable {qty}_avg equal f_avg_{qty}")
                            thermo_avg_keywords.append(f"v_{qty}_avg")

                    elif qty == 'ke':
                        if 'ke' not in computes_defined:
                            fixes_computes_lines.append("compute avg_ke_atom_compute all ke/atom")
                            fixes_computes_lines.append("compute avg_ke_total_compute all reduce sum c_avg_ke_atom_compute")
                            computes_defined.add('ke')
                        fixes_computes_lines.append(f"fix avg_ke all ave/time {nevery} {nrepeat} {nfreq} c_avg_ke_total_compute")
                        fixes_computes_lines.append("variable ke_avg equal f_avg_ke")
                        thermo_avg_keywords.append("v_ke_avg")

                    elif qty == 'pe':
                        if 'pe' not in computes_defined:
                            fixes_computes_lines.append("compute avg_pe_atom_compute all pe/atom")
                            fixes_computes_lines.append("compute avg_pe_total_compute all reduce sum c_avg_pe_atom_compute")
                            computes_defined.add('pe')
                        fixes_computes_lines.append(f"fix avg_pe all ave/time {nevery} {nrepeat} {nfreq} c_avg_pe_total_compute")
                        fixes_computes_lines.append("variable pe_avg equal f_avg_pe")
                        thermo_avg_keywords.append("v_pe_avg")

                if thermo_avg_keywords:
                    fixes_computes_lines.append("") # Add a blank line for readability
                    thermo_style += " " + " ".join(thermo_avg_keywords)
                
                fixes_computes_lines.append("")

                # Average Target Strain/Temp if averaging is active
                if output_config.get("add_target_to_thermo", False):
                    if mode == "Deformation":
                        fixes_computes_lines.append(f"fix avg_target_strain all ave/time {nevery} {nrepeat} {nfreq} v_estrain_{deform_axis}{deform_axis}")
                        fixes_computes_lines.append(f"variable target_strain_avg equal f_avg_target_strain")
                        thermo_style += " v_target_strain_avg"
                    else: # Temperature
                        points = deform_study.get("data_points", [])
                        initial_temp = points[0][1] if points else 300.0
                        fixes_computes_lines.append(f"variable set_temp equal {initial_temp}")
                        fixes_computes_lines.append(f"fix avg_target_temp all ave/time {nevery} {nrepeat} {nfreq} v_set_temp")
                        fixes_computes_lines.append(f"variable target_temp_avg equal f_avg_target_temp")
                        thermo_style += " v_target_temp_avg"

                fixes_computes_lines.append("")

            # Custom fixes
            if fixes_config.get("enable_custom_fixes", False):
                custom_fixes = fixes_config.get("custom_fixes", "")
                if custom_fixes:
                    fixes_computes_lines.extend([
                        "# Custom fixes",
                        custom_fixes,
                        ""
                    ])

            # Custom computes
            if output_config.get("enable_custom_computes", False):
                custom_computes = output_config.get("custom_computes", "")
                if custom_computes:
                    fixes_computes_lines.extend([
                        "# Custom computes",
                        custom_computes,
                        ""
                    ])
            
            if fixes_computes_lines:
                script_lines.extend([
                    "#------------------------",
                    "# Fixes & Computes",
                    "#------------------------",
                ])
                script_lines.extend(fixes_computes_lines)


            # Ensemble settings (specific to each study)
            ensemble_config = deform_study.get("ensemble", {})
            ensemble = ensemble_config.get("ensemble", "NVT")
            temp = ensemble_config.get("temperature", 300.0)
            pressure = ensemble_config.get("pressure", 1.0)
            
            # Velocity settings (specific to each study)
            if system_config.get("enable_velocity", True):
                script_lines.extend([
                    "#------------------------",
                    "# Ensemble settings (per study)",
                    "#------------------------"
                ])
                initial_velocity_seed = system_config.get("initial_velocity_seed", 12345)
                script_lines.extend([
                    "# Initial velocity",
                    f"velocity all create {temp} {initial_velocity_seed} mom yes rot yes dist gaussian",
                    ""
                ])
            
            # Bond breakage if enabled (per study)
            bond_breakage_config = deform_study.get("bond_breakage", {})
            if bond_breakage_config.get("enable_bond_breakage", False):
                nevery = bond_breakage_config.get("nevery", 1)
                bondtype = bond_breakage_config.get("bondtype", 1)
                rmax = bond_breakage_config.get("rmax", 1.5)
                enable_prob = bond_breakage_config.get("enable_prob", False)
                bond_break_cmd = f"fix break_all all bond/break {nevery} {bondtype} {rmax}"
                if enable_prob:
                    prob_fraction = bond_breakage_config.get("prob_fraction", 0.1)
                    prob_seed = bond_breakage_config.get("prob_seed", 12345)
                    bond_break_cmd += f" prob {prob_fraction} {prob_seed}"
                
                script_lines.extend([
                    "#------------------------",
                    "# Bond breakage",
                    "#------------------------",
                    bond_break_cmd,
                    ""
                ])

            # Additional output settings specific to this study
            trj_output_freq = output_config.get("traj_freq", 100)

            output_lines = []
            
            # Thermo output settings
            if output_config.get("enable_thermo", True):
                add_target_to_thermo = output_config.get("add_target_to_thermo", False)
                averaged_quantities = output_config.get("averaged_quantities", [])

                if add_target_to_thermo and not averaged_quantities:
                    if mode == "Deformation":
                        thermo_style += f" v_estrain_{deform_axis}{deform_axis}"
                    else: # Temperature
                        points = deform_study.get("data_points", [])
                        initial_temp = points[0][1] if points else 300.0
                        # Define variable right before it's used in thermo_style
                        output_lines.append(f"variable set_temp equal {initial_temp}")
                        thermo_style += " v_set_temp"
                
                output_lines.extend([
                    f"thermo {thermo_output_freq}",
                    f"thermo_style custom {thermo_style}",
                    "thermo_modify lost warn flush yes",
                    ""
                ])

            # Trajectory output settings
            if output_config.get("enable_trajectory", True):
                traj_format = output_config.get("traj_format", "lammpstrj")
                trj_output_items = output_config.get("trj_output_items", "id type x y z fx fy fz")
                output_lines.extend([
                    f"dump trajectory all custom {trj_output_freq} {model_name}.{traj_format} {trj_output_items}",
                    ""
                ])

            # Custom computes
            if output_config.get("enable_custom_computes", False):
                custom_computes = output_config.get("custom_computes", "")
                if custom_computes:
                    output_lines.extend([
                        "# Custom computes",
                        custom_computes,
                        ""
                    ])

            # Custom dumps
            custom_dumps = output_config.get("custom_dumps", "")
            if custom_dumps:
                    output_lines.extend([
                        "# Custom dumps",
                        custom_dumps,
                        ""
                    ])
            
            # Only add the heading if there are output settings
            if output_lines:
                script_lines.extend([
                    "#------------------------",
                    "# Output settings",
                    "#------------------------"
                ])
                script_lines.extend(output_lines)
            
            # Deformation
            script_lines.extend([
                "#------------------------",
                "# Deformation",
                "#------------------------",
                f"print \"Initial box boundaries: {deform_axis}lo = ${{{deform_axis}lo0}}, {deform_axis}hi = ${{{deform_axis}hi0}}, length = ${{L0{deform_axis}}}\"",
                ""
            ])

            points = deform_study.get("data_points", [])
            mode = deform_study.get("mode", "Deformation")

            if len(points) > 1:
                timestep = system_config.get("timestep", 0.001)
                deform_axis = deform_study.get("deform_axis", "x")
                


                for i in range(len(points) - 1):
                    p1 = points[i]
                    p2 = points[i+1]

                    start_step = p1[0]
                    end_step = p2[0]
                    duration = end_step - start_step

                    if duration <= 0:
                        continue

                    start_y = p1[1]
                    end_y = p2[1]
                    y_change = end_y - start_y

                    script_lines.append(f"# --- Segment {i+1}: from step {start_step:.0f} to {end_step:.0f} ---")



                    if mode == "Deformation":
                        # Calculate new boundaries based on engineering strain from initial state
                        new_lo_var = f"{deform_axis}lo_target_{i+1}"
                        new_hi_var = f"{deform_axis}hi_target_{i+1}"
                        
                        deform_scenario = deform_study.get("deform_scenario", "symmetric")
                        script_lines.append(f"# Target engineering strain: {end_y:.6f}, Scenario: {deform_scenario}")

                        if deform_scenario == "shift hi, fix lo":
                            script_lines.append(f"variable {new_lo_var} equal v_{deform_axis}lo0")
                            script_lines.append(f'variable {new_hi_var} equal "v_{deform_axis}hi0 + (v_L0{deform_axis} * {end_y})"')
                        elif deform_scenario == "shift lo, fix hi":
                            script_lines.append(f'variable {new_lo_var} equal "v_{deform_axis}lo0 - (v_L0{deform_axis} * {end_y})"')
                            script_lines.append(f"variable {new_hi_var} equal v_{deform_axis}hi0")
                        else:  # symmetric
                            script_lines.append(f'variable {new_lo_var} equal "v_{deform_axis}lo0 - (v_L0{deform_axis} * {end_y}) / 2"')
                            script_lines.append(f'variable {new_hi_var} equal "v_{deform_axis}hi0 + (v_L0{deform_axis} * {end_y}) / 2"')
                        
                        script_lines.append(f"print \"Segment {i+1}: Target boundaries: {deform_axis}lo = ${{{new_lo_var}}}, {deform_axis}hi = ${{{new_hi_var}}}\"")

                        if abs(y_change) > 1e-12:
                            script_lines.append(f"fix deform all deform 1 {deform_axis} final ${{{new_lo_var}}} ${{{new_hi_var}}} units box")

                        # Apply ensemble for this segment
                        if ensemble == "NVT":
                            damping_factor = system_config.get("damping_factor", 100.0)
                            script_lines.append(f"fix nvt all nvt temp {temp} {temp} $({damping_factor}*dt)")
                        elif ensemble == "NPT":
                            damping_factor = system_config.get("damping_factor", 100.0)
                            npt_aniso = ensemble_config.get("npt_aniso", "iso")  # Get the new anisotropic setting
                            
                            script_lines.append(f"fix npt all npt temp {temp} {temp} $({damping_factor}*dt) {npt_aniso} {pressure} {pressure} $(1000*dt)")
                        
                        script_lines.append(f"run {int(duration)}")
                        
                        if ensemble in ["NVT", "NPT"]:
                            script_lines.append(f"unfix {ensemble.lower()}\n")

                        # Write data after this segment if requested
                        if output_config.get("write_data_option") == "After each deformation/temperature step":
                            base_name = Path(data_file).stem
                            write_data_filename = f"{base_name}_*.data"
                            script_lines.extend([
                                f"# Write data after segment {i+1}",
                                f"write_data {write_data_filename}",
                                ""
                            ])

                    elif mode == "Temperature":
                        # Apply ensemble with temperature ramp
                        if ensemble == "NVT":
                            damping_factor = system_config.get("damping_factor", 100.0)
                            script_lines.append(f"fix nvt all nvt temp {start_y} {end_y} $({damping_factor}*dt)")
                        elif ensemble == "NPT":
                            damping_factor = system_config.get("damping_factor", 100.0)
                            npt_aniso = ensemble_config.get("npt_aniso", "iso")  # Get the new anisotropic setting
                            
                            script_lines.append(f"fix npt all npt temp {start_y} {end_y} $({damping_factor}*dt) {npt_aniso} {pressure} {pressure} $(1000*dt)")

                        script_lines.append(f"run {int(duration)}")

                        if ensemble in ["NVT", "NPT"]:
                            script_lines.append(f"unfix {ensemble.lower()}\n")

                        # Write data after this segment if requested
                        if output_config.get("write_data_option") == "After each deformation/temperature step":
                            base_name = Path(data_file).stem
                            write_data_filename = f"{base_name}_*.data"
                            script_lines.extend([
                                f"# Write data after segment {i+1}",
                                f"write_data {write_data_filename}",
                                ""
                            ])

                    script_lines.append("")
            
            # Add write_data at the end if enabled
            write_data_option = output_config.get("write_data_option", "Never")
            if write_data_option == "At the end of the simulation":
                # Extract the base name from the data_file and use wildcard for timestep
                base_name = Path(data_file).stem
                
                write_data_filename = f"{base_name}_*.data"
                
                script_lines.extend([
                    "#------------------------",
                    "# Write final state to data file",
                    "#------------------------",
                    f"write_data {write_data_filename}",
                    ""
                ])
            

            
            full_script = "\n".join(script_lines)
            
            return full_script
            
        except Exception as e:
            return f"# Error generating script content: {str(e)}"
        
    def generate_execution_script(self, root_simulation_dir, system_files, deform_studies, is_multi_system):
        """Generate execution script for sequential multi-system processing"""
        try:
            import platform
            current_os = platform.system().lower()
            
            # Generate OS-specific script only
            if current_os in ['linux', 'darwin']:  # Linux or Mac
                exec_script_path = os.path.join(root_simulation_dir, "local_run_all.sh")
                script_lines = [
                    "#!/bin/bash",
                    "# Sequential execution script for multiple LAMMPS simulations",
                    "# For Linux/Mac systems - generated for " + current_os,
                    "",
                    "echo 'Starting sequential LAMMPS simulations...'",
                    ""
                ]
                command_prefix = "gnome-terminal -- bash -c '"
                command_suffix = "; exec bash'"  # Keep terminal open after command completes
            else:  # Windows
                exec_script_path = os.path.join(root_simulation_dir, "local_run_all.bat")
                script_lines = [
                    "@echo off",
                    "REM Sequential execution script for multiple LAMMPS simulations",
                    "REM For Windows systems",
                    "",
                    "echo 'Starting sequential LAMMPS simulations...'",
                    ""
                ]
                command_prefix = "start cmd /k "
                command_suffix = ""
            
            # Get execution mode
            job_submission_config = self.config.get("job_submission", {})
            local_lammps_cmd = job_submission_config.get("local_lammps_cmd", "lmp")
            use_multiprocessor = job_submission_config.get("local_multiprocessor", False)
            num_processors = job_submission_config.get("local_processors", 1)

            if use_multiprocessor:
                lammps_executable = job_submission_config.get("local_lammps_executable", "lmp_mpi")
                full_local_cmd = f"{local_lammps_cmd} -np {num_processors} {lammps_executable}"
            else:
                full_local_cmd = local_lammps_cmd

            if job_submission_config.get("enable_restart", False):
                full_local_cmd += " -var restart FALSE -var maxtime 86400"
            
            # Local execution should not have restart logic.
            for study in deform_studies:
                study_name = study.get("name", "study")
                
                for system_file in system_files:
                    system_name = Path(system_file).stem
                    model_name = f"{study_name}_{system_name}"  # Changed to study_name_first
                    
                    # Always use consistent file structure: study/system/model_name.in
                    script_relative_path = f"{study_name}/{system_name}/{model_name}.in"
                    sim_directory = f"{study_name}/{system_name}"
                    
                    # Local execution without restart - change to simulation directory and run in new terminal
                    if current_os in ['linux', 'darwin']:
                        script_lines.extend([
                            f"echo 'Running simulation: {model_name}'",
                            f"cd {sim_directory}",
                            f"{command_prefix}{full_local_cmd} -in {model_name}.in{command_suffix}",
                            f"echo 'Started simulation in new terminal: {model_name}'",
                            f"cd ../../",  # Go back to root directory
                            ""
                        ])
                    else:  # Windows
                        script_lines.extend([
                            f"echo 'Running simulation: {model_name}'",
                            f"cd {sim_directory}",
                            f"{command_prefix}{full_local_cmd} -in {model_name}.in{command_suffix}",
                            f"echo 'Started simulation in new terminal: {model_name}'",
                            f"cd ../../",  # Go back to root directory
                            ""
                        ])
            
            if current_os in ['linux', 'darwin']:
                script_lines.extend([
                    "echo 'All simulation terminals started!'",
                    "echo 'Each simulation runs in its own terminal window'",
                    ""
                ])
            else:
                script_lines.extend([
                    "echo 'All simulation terminals started!'",
                    "echo 'Each simulation runs in its own command prompt window'",
                    ""
                ])
            
            # Write execution script with UNIX line endings
            with open(exec_script_path, 'w', newline='\n') as f:
                f.write("\n".join(script_lines))
            
            # Make shell script executable for Linux/Mac
            if current_os in ['linux', 'darwin']:
                os.chmod(exec_script_path, 0o755)
            
            self.generated_files.append(exec_script_path)
            
            return {"success": True, "message": f"Execution script generated: {exec_script_path} (for {current_os})"}
            
        except Exception as e:
            return {"success": False, "message": f"Error generating execution script: {str(e)}"}
    
    def generate_cluster_submission_script(self, root_simulation_dir, system_files, deform_studies, is_multi_system):
        """Generate single master cluster job file and submission script"""
        try:
            # Create single master job file that accepts input file as argument
            master_job_path = os.path.join(root_simulation_dir, "lammps_simulation.job")
            
            # Get cluster settings
            job_submission_config = self.config.get("job_submission", {})
            cluster_lammps_cmd = job_submission_config.get("cluster_lammps_cmd", "lmp")
            srun_cmd = job_submission_config.get("srun_cmd", "srun")
            sbatch_cmd = job_submission_config.get("sbatch_cmd", "sbatch")
            slurm_header = job_submission_config.get("slurm_header", "#!/bin/bash\n -l#SBATCH --job-name=lammps_simulation\n#SBATCH --partition=singlenode\n#SBATCH --nodes=1\n#SBATCH --ntasks-per-node=72\n#SBATCH --cpus-per-task=1\n#SBATCH --time=24:00:00\n#SBATCH --export=NONE\n#SBATCH --output=lammps_output_%j.txt\n#SBATCH --error=lammps_error_%j.txt\n\nunset SLURM_EXPORT_ENV")

            # Check if restart functionality is enabled globally
            enable_restart = job_submission_config.get("enable_restart", False)
            
            if enable_restart:
                # Get max time buffer from configuration
                max_time_buffer = job_submission_config.get("max_time_buffer", 600)  # Default 10 minutes
                
                # Generate master job file that handles restart functionality according to HPC documentation
                job_lines = [
                    slurm_header,
                    "", 
                    "# Get input file path from first argument",
                    "input=$1",
                    "if [ -z \"$input\" ]; then",
                    "    echo 'Error: No input file specified'",
                    "    exit 1",
                    "fi",
                    "",
                    "# Extract model name from input file",
                    "MODEL_NAME=$(basename \"$input\" .in)",
                    "",
                    "# Calculate maxtime (24 hours - buffer in seconds)",
                    f"MAXTIME=$((24*3600-{max_time_buffer}))",
                    "",
                    "echo 'Running LAMMPS simulation: $MODEL_NAME'",
                    "echo 'Input file: $input'",
                    "",
                    "# Load modules",
                    f"module load {job_submission_config.get('module_load', 'lammps')}",
                    "",
                    "# Handle restart: check if restart files exist and use the latest one",
                    "cd \"$(dirname \"$input\")\"  # Change to the directory containing the input file",
                    "",
                    "# Check if restart files exist for this model",
                    "if compgen -G \"restart_files/${MODEL_NAME}.restart.*\" > /dev/null; then",
                    "  # Find the latest restart file",
                    "  latest_restart=$(ls restart_files/${MODEL_NAME}.restart.* | sort -V | tail -n 1)",
                    "  echo \"Found restart file: $latest_restart\"",
                    "  echo \"Moving $latest_restart to restart_files/${MODEL_NAME}.restart for LAMMPS to use\"",
                    "  mv \"$latest_restart\" \"restart_files/${MODEL_NAME}.restart\"",
                    "  # Run LAMMPS with restart flag set to TRUE",
                    f"  {srun_cmd} {cluster_lammps_cmd} -in \"$input\" -var restart TRUE -var maxtime $MAXTIME",
                    "else",
                    "  # No restart files, run initial simulation",
                    f"  {srun_cmd} {cluster_lammps_cmd} -in \"$input\" -var restart FALSE -var maxtime $MAXTIME",
                    "fi",
                    "",
                                        "# Check if a restart file was created, indicating the job was halted and should be resubmitted.",
                                        "if compgen -G \"restart_files/${MODEL_NAME}.restart.*\" > /dev/null; then",
                                        "  # Check if the job ran for a minimum amount of time to avoid restart loops on immediate failure.",
                                        "  if [ \"$SECONDS\" -gt 60 ]; then",
                                        "    echo \"Restart file found and job ran long enough. Resubmitting.\"",
                                        "    cd \"$SLURM_SUBMIT_DIR\"",
                                        f"    {sbatch_cmd} --job-name=\"$SLURM_JOB_NAME\" \"$SLURM_SUBMIT_DIR/lammps_simulation.job\" \"$input\"",
                                        "    echo \"Killing current job...\"",
                                        "    scancel $SLURM_JOB_ID",
                                        "  else",
                                        "    echo \"WARNING: Job took less than 60s, no resubmission to prevent loops!\"",
                                        "  fi",
                                        "fi",
                                        "",
                                        "cd \"$SLURM_SUBMIT_DIR\"",
                                        "echo 'Completed simulation: $MODEL_NAME'",                 ]
            else:
                # Generate simple job file without restart functionality
                job_lines = [
                    slurm_header,
                    "", 
                    "# Get input file path from first argument",
                    "input=$1",
                    "if [ -z \"$input\" ]; then",
                    "    echo 'Error: No input file specified'",
                    "    exit 1",
                    "fi",
                    "",
                    "echo 'Running LAMMPS simulation with input: $input'",
                    "",
                    "# Load modules",
                    f"module load {job_submission_config.get('module_load', 'lammps')}",
                    "",                
                    "# Run LAMMPS with input file",
                    f"{srun_cmd} {cluster_lammps_cmd} -in \"$input\"",
                    
                    "echo 'Completed simulation for: $input'",
                ]
            
            # Write master job file with UNIX line endings
            with open(master_job_path, 'w', newline='\n') as f:
                f.write("\n".join(job_lines))
            
            os.chmod(master_job_path, 0o755)
            self.generated_files.append(master_job_path)
            
            # Generate cluster submission script (Linux only - clusters are always Linux)
            cluster_script_path = os.path.join(root_simulation_dir, "cluster_run_jobs.sh")
            
            script_lines = [
                "#!/bin/bash",
                "# Cluster job submission script for multiple LAMMPS simulations",
                "# This script uses a single master job file with different input files",
                "# For Linux cluster systems only",
                "",
                "echo 'Starting cluster job submissions...'",
                ""
            ]
            
            # Add commands for each simulation
            for study in deform_studies:
                study_name = study.get("name", "study")
                
                for system_file in system_files:
                    system_name = Path(system_file).stem
                    model_name = f"{study_name}_{system_name}"  # Changed to study_name_first
                    
                    # Determine input file path and directory
                    input_file_path = f"{model_name}.in"
                    sim_directory = f"{study_name}/{system_name}"
                    
                    script_lines.extend([
                        f"cd {sim_directory}",
                        f"{sbatch_cmd} --job-name=\"{model_name}\" --mail-type=ALL \"../../lammps_simulation.job\" \"{input_file_path}\"",
                        f"cd ../../",
                        ""
                    ])
            
            script_lines.extend([
                "echo 'All cluster jobs submitted!'",
                "echo 'Use squeue to monitor job status'",
                ""
            ])
            
            # Write cluster submission script with UNIX line endings
            with open(cluster_script_path, 'w', newline='\n') as f:
                f.write("\n".join(script_lines))
            
            os.chmod(cluster_script_path, 0o755)
            self.generated_files.append(cluster_script_path)
            
            return {"success": True, "message": f"Master job file: {master_job_path}, Cluster script: {cluster_script_path}"}
            
        except Exception as e:
            return {"success": False, "message": f"Error generating cluster submission scripts: {str(e)}"}
        
    def generate_base_settings_file(self, root_simulation_dir):
        """Generate baseSettings.in file with common LAMMPS configuration"""
        try:
            system_config = self.config.get("system", {})
            fixes_config = self.config.get("fixes", {})
            output_config = self.config.get("output", {})
            
            units = system_config.get("units", "metal")
            
            base_settings_lines = [
                "#------------------------",
                "# Basic LAMMPS settings",
                "#------------------------",
                f"units {units}",
                f"atom_style {system_config.get('atom_style', 'atomic')}",
                "processors * * *",
                "dimension 3",
                f"boundary {system_config.get('boundary_x', 'p')} {system_config.get('boundary_y', 'p')} {system_config.get('boundary_z', 'p')}",
                ""
            ]
            
            # Ensemble settings
            # Note: We can't add temperature/ensemble settings here since they vary per study
            timestep = system_config.get("timestep", 0.001)
            base_settings_lines.extend([
                "#------------------------",
                "# Ensemble settings",
                "#------------------------",
                "# Timestep",
                f"timestep {timestep}",
                ""
            ])
            
            # Neighbor settings
            neighbor_distance = system_config.get("neighbor_distance", 0.3)
            enable_neighbor_distance = system_config.get("enable_neighbor_distance", True)
            
            neigh_modify_every = system_config.get("neigh_modify_every", 1)
            enable_neigh_modify_every = system_config.get("enable_neigh_modify_every", True)
            
            neigh_modify_delay = system_config.get("neigh_modify_delay", 10)
            enable_neigh_modify_delay = system_config.get("enable_neigh_modify_delay", True)
            
            neigh_modify_check = system_config.get("neigh_modify_check", "yes")
            enable_neigh_modify_check = system_config.get("enable_neigh_modify_check", True)
            
            neigh_modify_one = system_config.get("neigh_modify_one", 0)
            enable_neigh_modify_one = system_config.get("enable_neigh_modify_one", False)
            
            base_settings_lines.extend([
                "#------------------------",
                "# Neighbor settings",
                "#------------------------",
            ])
            
            # Add neighbor command if enabled
            if enable_neighbor_distance:
                base_settings_lines.extend([
                    f"neighbor {neighbor_distance} bin",
                ])
            
            # Build neigh_modify command based on enabled options
            neigh_modify_parts = ["neigh_modify"]
            any_neigh_modify_enabled = False
            
            if enable_neigh_modify_every:
                neigh_modify_parts.append(f"every {neigh_modify_every}")
                any_neigh_modify_enabled = True
                
            if enable_neigh_modify_delay:
                neigh_modify_parts.append(f"delay {neigh_modify_delay}")
                any_neigh_modify_enabled = True
                
            if enable_neigh_modify_check:
                neigh_modify_parts.append(f"check {neigh_modify_check}")
                any_neigh_modify_enabled = True
                
            if enable_neigh_modify_one:
                neigh_modify_parts.append(f"one {neigh_modify_one}")
                any_neigh_modify_enabled = True
            
            if any_neigh_modify_enabled:
                base_settings_lines.extend([
                    " ".join(neigh_modify_parts),
                ])
            
            base_settings_lines.extend([""])
            
            # We can't include velocity creation here since it might vary per study
            # We'll handle initial velocity in the individual study files
            
            # Create the base_input.in file
            base_settings_file = os.path.join(root_simulation_dir, "base_input.in")
            
            with open(base_settings_file, 'w') as f:
                f.write("\n".join(base_settings_lines))
            
            self.generated_files.append(base_settings_file)
            
            return {"success": True, "message": f"Base settings file generated: {base_settings_file}", "file_path": base_settings_file}
            
        except Exception as e:
            return {"success": False, "message": f"Error generating base settings file: {str(e)}"}
        
    def read_units_from_data_file(self, data_file):
        """Read units from LAMMPS data file"""
        try:
            with open(data_file, 'r') as f:
                for line in f:
                    if "units =" in line:
                        # Extract units value
                        parts = line.split("units =")
                        if len(parts) > 1:
                            units = parts[1].strip()
                            return units
        except Exception as e:
            print(f"Warning: Could not read units from data file: {str(e)}")
        
        # Default units if not found
        return "metal"