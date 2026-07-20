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
            
            # Create input_files folder and copy all data files there
            data_files_folder = os.path.join(root_simulation_dir, "input_files")
            os.makedirs(data_files_folder, exist_ok=True)
            
            # Copy all data files to input_files
            data_file_dest_paths = {}
            for i, system_file in enumerate(system_files):
                system_name = Path(system_file).stem
                data_file_dest = os.path.join(data_files_folder, f"{system_name}.data")
                shutil.copy2(system_file, data_file_dest)
                data_file_dest_paths[system_file] = (Path("input_files") / f"{system_name}.data").as_posix()
                
                # Copy potential file if used
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
            job_submission_config = self.config.get("job_submission", {})
            
            units = system_config.get("units", "metal")
            
            script_lines = [
                f"# {model_name}.in",
                f"# Generated by LAMMPS Input Script Generator on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                ""
            ]
            
            # Basic LAMMPS settings
            script_lines.extend([
                "#------------------------",
                "# Basic LAMMPS settings",
                "#------------------------",
                f"units {units}",
                f"atom_style {system_config.get('atom_style', 'atomic')}",
                "processors * * *",
                "dimension 3",
                f"boundary {system_config.get('boundary_x', 'p')} {system_config.get('boundary_y', 'p')} {system_config.get('boundary_z', 'p')}",
                ""
            ])
            
            # Read data and set (optional) potentials
            script_lines.extend([
                "#------------------------",
                "# Read data and set (optional) potentials",
                "#------------------------"
            ])

            if job_submission_config.get("enable_restart", False):
                script_lines.extend([
                    'variable restart_file string "positions.restart"',
                    'if "${restart} == TRUE" then &',
                    '    "read_restart ${restart_file}" & ',
                    'else & ',
                    f'   "read_data ../../{data_file}"'
                ])
            else:
                script_lines.append(f"read_data ../../{data_file}")
            
            if system_config.get("use_potential_file", False):
                potential_file = system_config.get("potential_file", "")
                if potential_file:
                    potential_name = Path(potential_file).name
                    potential_path = (Path("input_files") / potential_name).as_posix()
                    script_lines.append(f"include ../../{potential_path}")
            script_lines.append("")
            
            # Neighbor settings & atom images
            neighbor_distance = system_config.get("neighbor_distance", 0.3)
            neigh_modify_every = system_config.get("neigh_modify_every", 1)
            neigh_modify_delay = system_config.get("neigh_modify_delay", 10)
            neigh_modify_check = system_config.get("neigh_modify_check", True)
            
            script_lines.extend([
                "#------------------------",
                "# Neighbor settings & atom images",
                "#------------------------",
                "reset_atoms image all",
                f"neighbor {neighbor_distance} bin",
                f"neigh_modify every {neigh_modify_every} delay {neigh_modify_delay} {'check yes' if neigh_modify_check else 'check no'}",
                ""
            ])

            if job_submission_config.get("enable_restart", False):
                restart_freq = job_submission_config.get("restart_freq", 1000)
                halt_freq = job_submission_config.get("halt_freq", 100)
                script_lines.extend([
                    "#------------------------",
                    "# Restart settings",
                    "#------------------------",
                    f"restart {restart_freq} positions.restart",
                    f'fix stop all halt {halt_freq} tlimit > ${{maxtime}}',
                    ""
                ])

            # Ensemble settings
            ensemble_config = deform_study.get("ensemble", {})
            ensemble = ensemble_config.get("ensemble", "NVT")
            temp = ensemble_config.get("temperature", 300.0)
            pressure = ensemble_config.get("pressure", 1.0)
            
            script_lines.extend([
                "#------------------------",
                "# Ensemble settings",
                "#------------------------"
            ])
            
            if system_config.get("enable_velocity", True):
                initial_velocity_seed = system_config.get("initial_velocity_seed", 12345)
                script_lines.extend([
                    "# Initial velocity",
                    f"velocity all create {temp} {initial_velocity_seed} mom yes rot yes dist gaussian",
                    ""
                ])
            
            timestep = system_config.get("timestep", 0.001)
            script_lines.extend([
                "# Timestep",
                f"timestep {timestep}",
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

            # Output settings
            thermo_output_freq = output_config.get("thermo_freq", 100)
            trj_output_freq = output_config.get("thermo_freq", 1000)

            script_lines.extend([
                "#------------------------",
                "# Output settings",
                "#------------------------"
            ])

            if output_config.get("enable_thermo", True):
                thermo_style = output_config.get("thermo_style", "step etotal pe ke epair ebond evdwl ecoul elong temp press pxx pyy pzz pxy pxz pyz lx ly lz density")
                script_lines.extend([
                    f"thermo {thermo_output_freq}",
                    f"thermo_style custom {thermo_style}",
                    "thermo_modify lost warn flush yes",
                    ""
                ])

            if output_config.get("enable_custom_computes", False):
                custom_computes = output_config.get("custom_computes", "")
                if custom_computes:
                    script_lines.extend([
                        "# Custom computes",
                        custom_computes,
                        ""
                    ])

            if output_config.get("enable_trajectory", True):
                traj_format = output_config.get("traj_format", "lammpstrj")
                trj_output_items = output_config.get("trj_output_items", "id type x y z fx fy fz")
                script_lines.extend([
                    f"dump trajectory all custom {trj_output_freq} {model_name}.{traj_format} {trj_output_items}",
                    ""
                ])

            if output_config.get("enable_custom_dumps", False):
                custom_dumps = output_config.get("custom_dumps", "")
                if custom_dumps:
                    script_lines.extend([
                        "# Custom dumps",
                        custom_dumps,
                        ""
                    ])
            
            # Deformation
            script_lines.extend([
                "#------------------------",
                "# Deformation",
                "#------------------------"
            ])

            points = deform_study.get("data_points", [])
            mode = deform_study.get("mode", "Deformation")

            if len(points) > 1:
                timestep = system_config.get("timestep", 0.001)
                deform_axis = deform_study.get("deform_axis", "x")
                
                if mode == "Deformation":
                    # Store initial box boundaries for symmetric deformation
                    script_lines.append(f"# Store initial box boundaries for symmetric engineering strain calculation")
                    script_lines.append(f"variable {deform_axis}lo0 equal $({deform_axis}lo)")
                    script_lines.append(f"variable {deform_axis}hi0 equal $({deform_axis}hi)")
                    script_lines.append(f"variable L0 equal $(l{deform_axis})")
                    script_lines.append(f"print \"Initial box boundaries: {deform_axis}lo = ${{{deform_axis}lo0}}, {deform_axis}hi = ${{{deform_axis}hi0}}, length = ${{L0}}\"")
                    script_lines.append("")
                
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
                            script_lines.append(f"variable {new_lo_var} equal \"v_{deform_axis}lo0\"")
                            script_lines.append(f"variable {new_hi_var} equal \"v_{deform_axis}hi0 + (v_L0 * {end_y})\"")
                        elif deform_scenario == "shift lo, fix hi":
                            script_lines.append(f"variable {new_lo_var} equal \"v_{deform_axis}lo0 - (v_L0 * {end_y})\"")
                            script_lines.append(f"variable {new_hi_var} equal \"v_{deform_axis}hi0\"")
                        else:  # symmetric
                            script_lines.append(f"variable {new_lo_var} equal \"v_{deform_axis}lo0 - (v_L0 * {end_y}) / 2\"")
                            script_lines.append(f"variable {new_hi_var} equal \"v_{deform_axis}hi0 + (v_L0 * {end_y}) / 2\"")
                        
                        script_lines.append(f"print \"Segment {i+1}: Target boundaries: {deform_axis}lo = ${{{new_lo_var}}}, {deform_axis}hi = ${{{new_hi_var}}}\"")

                        if abs(y_change) > 1e-12:
                            script_lines.append(f"fix deform all deform 1 {deform_axis} final ${{{new_lo_var}}} ${{{new_hi_var}}} units box")

                        # Apply ensemble for this segment
                        if ensemble == "NVT":
                            damping_factor = system_config.get("damping_factor", 100.0)
                            script_lines.append(f"fix nvt all nvt temp {temp} {temp} $({damping_factor}*dt)")
                        elif ensemble == "NPT":
                            damping_factor = system_config.get("damping_factor", 100.0)
                            npt_keyword = ""
                            if deform_axis == 'x':
                                npt_keyword = f"y {pressure} {pressure} $(1000*dt) z {pressure} {pressure} $(1000*dt)"
                            elif deform_axis == 'y':
                                npt_keyword = f"x {pressure} {pressure} $(1000*dt) z {pressure} {pressure} $(1000*dt)"
                            elif deform_axis == 'z':
                                npt_keyword = f"x {pressure} {pressure} $(1000*dt) y {pressure} {pressure} $(1000*dt)"
                            else:
                                npt_keyword = f"iso {pressure} {pressure} $(1000*dt)"
                            script_lines.append(f"fix npt all npt temp {temp} {temp} $({damping_factor}*dt) {npt_keyword}")
                        
                        script_lines.append(f"run {int(duration)}")
                        
                        if abs(y_change) > 1e-12:
                            script_lines.append("unfix deform")
                        
                        if ensemble in ["NVT", "NPT"]:
                            script_lines.append(f"unfix {ensemble.lower()}")

                    elif mode == "Temperature":
                        # Apply ensemble with temperature ramp
                        if ensemble == "NVT":
                            damping_factor = system_config.get("damping_factor", 100.0)
                            script_lines.append(f"fix nvt all nvt temp {start_y} {end_y} $({damping_factor}*dt)")
                        elif ensemble == "NPT":
                            damping_factor = system_config.get("damping_factor", 100.0)
                            npt_keyword = f"iso {pressure} {pressure} $(1000*dt)"
                            script_lines.append(f"fix npt all npt temp {start_y} {end_y} $({damping_factor}*dt) {npt_keyword}")

                        script_lines.append(f"run {int(duration)}")

                        if ensemble in ["NVT", "NPT"]:
                            script_lines.append(f"unfix {ensemble.lower()}")

                    script_lines.append("")
            
            # Add write_data at the end if enabled
            if output_config.get("enable_write_data", False):
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
                exec_script_path = os.path.join(root_simulation_dir, "run_local_all.sh")
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
                exec_script_path = os.path.join(root_simulation_dir, "run_local_all.bat")
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
            
            for study in deform_studies:
                study_name = study.get("name", "study")
                
                for system_file in system_files:
                    system_name = Path(system_file).stem
                    model_name = f"{study_name}_{system_name}"  # Changed to study_name_first
                    
                    # Always use consistent file structure: study/system/model_name.in
                    script_relative_path = f"{study_name}/{system_name}/{model_name}.in"
                    sim_directory = f"{study_name}/{system_name}"
                    
                    # Local execution - change to simulation directory and run in new terminal
                    if current_os in ['linux', 'darwin']:
                        script_lines.extend([
                            f"echo 'Running simulation: {model_name}'",
                            f"cd {sim_directory}",
                            f"{command_prefix}{local_lammps_cmd} -in {model_name}.in{command_suffix}",
                            f"echo 'Started simulation in new terminal: {model_name}'",
                            f"cd ../../",  # Go back to root directory
                            ""
                        ])
                    else:  # Windows
                        script_lines.extend([
                            f"echo 'Running simulation: {model_name}'",
                            f"cd {sim_directory}",
                            f"{command_prefix}{local_lammps_cmd} -in {model_name}.in{command_suffix}",
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
        """Generate cluster submission scripts, handling restartable jobs if enabled."""
        job_submission_config = self.config.get("job_submission", {})
        enable_restart = job_submission_config.get("enable_restart", False)

        if enable_restart:
            return self.generate_restartable_cluster_jobs(root_simulation_dir, system_files, deform_studies)
        else:
            return self.generate_master_cluster_job(root_simulation_dir, system_files, deform_studies)

    def generate_master_cluster_job(self, root_simulation_dir, system_files, deform_studies):
        """Generate a single master job file and a submission script (original behavior)."""
        try:
            # Create single master job file that accepts input file as argument
            master_job_path = os.path.join(root_simulation_dir, "lammps_simulation.job")
            
            # Get cluster settings
            job_submission_config = self.config.get("job_submission", {})
            cluster_lammps_cmd = job_submission_config.get("cluster_lammps_cmd", "lmp")
            srun_cmd = job_submission_config.get("srun_cmd", "srun")
            sbatch_cmd = job_submission_config.get("sbatch_cmd", "sbatch")
            slurm_header = job_submission_config.get("slurm_header", "#!/bin/bash -l\n#SBATCH --job-name=lammps_simulation\n#SBATCH --partition=singlenode\n#SBATCH --nodes=1\n#SBATCH --ntasks-per-node=72\n#SBATCH --cpus-per-task=1\n#SBATCH --time=24:00:00\n#SBATCH --export=NONE\n#SBATCH --output=lammps_output_%j.txt\n#SBATCH --error=lammps_error_%j.txt\n\nunset SLURM_EXPORT_ENV")

            # Generate master job file that accepts input file as argument
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
                "echo 'Running LAMMPS simulation: $MODEL_NAME'",
                "echo 'Input file: $input'",
                "",
                "# Load modules",
                f"module load {job_submission_config.get('module_load', 'lammps')}",
                "",                
                "# Run LAMMPS with input file",
                f'{srun_cmd} {cluster_lammps_cmd} -in \"$input.in\"',
                "",
                "echo 'Completed simulation: $MODEL_NAME'",
            ]
            
            # Write master job file with UNIX line endings
            with open(master_job_path, 'w', newline='\n') as f:
                f.write("\n".join(job_lines))
            
            os.chmod(master_job_path, 0o755)
            self.generated_files.append(master_job_path)
            
            # Generate cluster submission script (Linux only - clusters are always Linux)
            cluster_script_path = os.path.join(root_simulation_dir, "run_cluster_jobs.sh")
            
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
                    model_name = f"{study_name}_{system_name}"
                    
                    sim_directory = f"{study_name}/{system_name}"
                    
                    script_lines.extend([
                        f"cd {sim_directory}",
                        f'{sbatch_cmd} --job-name=\"{model_name}\" --mail-type=ALL \"../../lammps_simulation.job\" \"{model_name}\"',
                        f"cd ../../",
                        ""
                    ])
            
            script_lines.extend([
                "echo 'All cluster jobs submitted!'",
                "echo 'Use squeue to monitor job status'",
                ""
            ])
            
            with open(cluster_script_path, 'w', newline='\n') as f:
                f.write("\n".join(script_lines))
            
            os.chmod(cluster_script_path, 0o755)
            self.generated_files.append(cluster_script_path)
            
            return {"success": True, "message": f"Master job file: {master_job_path}, Cluster script: {cluster_script_path}"}
            
        except Exception as e:
            return {"success": False, "message": f"Error generating cluster submission scripts: {str(e)}"}

    def generate_restartable_cluster_jobs(self, root_simulation_dir, system_files, deform_studies):
        """Generate individual, restartable job scripts and a main submission script."""
        try:
            job_submission_config = self.config.get("job_submission", {})
            sbatch_cmd = job_submission_config.get("sbatch_cmd", "sbatch")

            cluster_script_path = os.path.join(root_simulation_dir, "run_cluster_jobs.sh")
            submission_script_lines = [
                "#!/bin/bash",
                "# Cluster job submission script for multiple restartable LAMMPS simulations",
                "",
                "echo 'Starting cluster job submissions...'",
                ""
            ]

            for study in deform_studies:
                study_name = study.get("name", "study")
                for system_file in system_files:
                    system_name = Path(system_file).stem
                    model_name = f"{study_name}_{system_name}"
                    
                    job_script_name = f"{model_name}.job"
                    job_script_path = os.path.join(root_simulation_dir, job_script_name)

                    self.generate_single_restartable_job_script(job_script_path, model_name, study_name, system_name)

                    submission_script_lines.extend([
                        f"cd {study_name}/{system_name}",
                        f"{sbatch_cmd} ../../{job_script_name}",
                        f"cd ../../",
                        ""
                    ])

            submission_script_lines.extend([
                "echo 'All cluster jobs submitted!'",
                "echo 'Use squeue to monitor job status'",
                ""
            ])

            with open(cluster_script_path, 'w', newline='\n') as f:
                f.write("\n".join(submission_script_lines))
            
            os.chmod(cluster_script_path, 0o755)
            self.generated_files.append(cluster_script_path)

            return {"success": True, "message": "Restartable cluster scripts generated."}
        except Exception as e:
            return {"success": False, "message": f"Error generating restartable cluster scripts: {str(e)}"}

    def generate_single_restartable_job_script(self, job_script_path, model_name, study_name, system_name):
        """Generates a single SLURM job script with restart logic."""
        job_submission_config = self.config.get("job_submission", {})
        slurm_header = job_submission_config.get("slurm_header", "")
        
        slurm_header_lines = [line for line in slurm_header.split('\n') if not line.strip().startswith('#SBATCH --job-name')]
        slurm_header = "\n".join(slurm_header_lines)

        max_time_buffer = job_submission_config.get("max_time_buffer", 600)
        module_load = job_submission_config.get("module_load", "lammps")
        srun_cmd = job_submission_config.get("srun_cmd", "srun")
        cluster_lammps_cmd = job_submission_config.get("cluster_lammps_cmd", "lmp")
        sbatch_cmd = job_submission_config.get("sbatch_cmd", "sbatch")

        job_script_name = os.path.basename(job_script_path)
        input_file = f"{model_name}.in"

        script_content = f'''{slurm_header}
#SBATCH --job-name={model_name}

unset SLURM_EXPORT_ENV

# Change to the simulation directory
cd {study_name}/{system_name}

# load required modules
module load {module_load}
MAXTIME=$((24*3600-{max_time_buffer}))

# run lammps
if compgen -G "positions.restart.*" > /dev/null; then
  filename=$(ls positions.restart.* |sort -V |tail -n 1)
  mv -v $filename positions.restart
  {srun_cmd} {cluster_lammps_cmd} -i {input_file} -var restart TRUE -var maxtime $MAXTIME
else
  {srun_cmd} {cluster_lammps_cmd} -i {input_file} -var restart FALSE -var maxtime $MAXTIME
fi

if [ "$SECONDS" -gt "3600" ]; then
  cd ${{SLURM_SUBMIT_DIR}}
  {sbatch_cmd} ../../{job_script_name}
fi
'''
        with open(job_script_path, 'w', newline='\n') as f:
            f.write(script_content)
        
        os.chmod(job_script_path, 0o755)
        self.generated_files.append(job_script_path)

        
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