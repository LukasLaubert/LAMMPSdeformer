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
            multistudy_config = self.config.get("multistudy", {})
            if not isinstance(multistudy_config, dict):
                return {"success": False, "message": "Invalid multistudy configuration"}
                
            deform_studies = multistudy_config.get("deform_studies", [])
            if not isinstance(deform_studies, list):
                return {"success": False, "message": "Invalid deformation studies configuration"}
                
            if not deform_studies:
                return {"success": False, "message": "No deformation studies defined"}
            
            # Validate each deformation study
            for i, study in enumerate(deform_studies):
                if not isinstance(study, dict):
                    return {"success": False, "message": f"Invalid deformation study at index {i}"}
                
                required_fields = ["name", "points", "max_steps", "min_strain", "max_strain", "thermo_freq"]
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
                data_file_dest_paths[system_file] = os.path.join("input_files", f"{system_name}.data")
                
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
            
            # Get units from config or read from data file
            units = system_config.get("units", "metal")
            if units == "auto":
                units = self.read_units_from_data_file(data_file)
            
            # Start with the basic template
            script_lines = [
                f"# {model_name}.in",
                f"# Generated by LAMMPS Input Script Generator on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                ""
            ]
            
            # Add basic LAMMPS settings
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
            
            # Add data file and potentials
            script_lines.extend([
                "#------------------------",
                "# Read data and set (optional) potentials",
                "#------------------------",
                f"read_data ../../{data_file}"
            ])
            
            if system_config.get("use_potential_file", False):
                potential_file = system_config.get("potential_file", "")
                potential_name = Path(potential_file).name
                # Always use relative path to input_files folder (go up two levels from study/system folder)
                script_lines.append(f"include ../../input_files/{potential_name}")
            script_lines.append("")
            
            # Add neighbor settings
            neighbor_distance = system_config.get("neighbor_distance", 0.3)
            neigh_modify_every = system_config.get("neigh_modify_every", 1)
            neigh_modify_delay = system_config.get("neigh_modify_delay", 10)
            neigh_modify_check = system_config.get("neigh_modify_check", True)
            
            script_lines.extend([
                "#------------------------",
                "# Neighbor settings",
                "#------------------------",
                f"neighbor {neighbor_distance} bin",
                f"neigh_modify every {neigh_modify_every} delay {neigh_modify_delay} {'check yes' if neigh_modify_check else 'check no'}",
                ""
            ])
            
            # Add ensemble settings
            ensemble = system_config.get("ensemble", "NVT")
            temp_init = system_config.get("temp_init", 300.0)
            temp_end = system_config.get("temp_end", 300.0)
            
            script_lines.extend([
                "#------------------------",
                "# Ensemble settings",
                "#------------------------"
            ])
            
            # Velocity initialization (optional)
            if system_config.get("enable_velocity", True):
                initial_velocity_seed = system_config.get("initial_velocity_seed", 12345)
                damping_factor = system_config.get("damping_factor", 100.0)
                
                script_lines.extend([
                    "# Initial velocity",
                    f"velocity all create {temp_init} {initial_velocity_seed} dist gaussian loop geom",
                    ""
                ])
            
            # Timestep
            timestep = system_config.get("timestep", 0.001)
            script_lines.extend([
                "# Timestep",
                f"timestep {timestep}",
                ""
            ])
            
            # Ensemble-specific fixes
            if ensemble == "NVT":
                if system_config.get("enable_velocity", True):
                    damping_factor = system_config.get("damping_factor", 100.0)
                    script_lines.extend([
                        "# NVT ensemble",
                        f"fix nvt all nvt temp {temp_init} {temp_end} $({damping_factor}*dt)",
                        ""
                    ])
                else:
                    script_lines.extend([
                        "# NVT ensemble",
                        f"fix nvt all nvt temp {temp_init} {temp_end} 0.1",
                        ""
                    ])
            elif ensemble == "NPT":
                pressure = system_config.get("pressure", 1.0)
                if system_config.get("enable_velocity", True):
                    damping_factor = system_config.get("damping_factor", 100.0)
                    script_lines.extend([
                        "# NPT ensemble",
                        f"fix npt all npt temp {temp_init} {temp_end} $({damping_factor}*dt) iso {pressure} {pressure} 1.0",
                        ""
                    ])
                else:
                    script_lines.extend([
                        "# NPT ensemble",
                        f"fix npt all npt temp {temp_init} {temp_end} 0.1 iso {pressure} {pressure} 1.0",
                        ""
                    ])
            
            # Deformation
            script_lines.extend([
                "#------------------------",
                "# Deformation",
                "#------------------------"
            ])
            
            points = deform_study.get("points", [])
            if len(points) > 1:
                for i in range(len(points) - 1):
                    p1 = points[i]
                    p2 = points[i+1]
                    
                    # Segment details
                    start_step = p1[0]
                    end_step = p2[0]
                    duration = end_step - start_step
                    
                    if duration <= 0:
                        continue

                    start_strain = p1[1]
                    end_strain = p2[1]

                    strain_change = end_strain - start_strain

                    # Strain rate in 1/time units
                    strain_rate = strain_change / (duration * timestep) if (duration * timestep) > 0 else 0

                    script_lines.append(f"# --- Segment {i+1}: from step {start_step} to {end_step} ---")

                    # Unfix previous deform fix if it exists
                    if i > 0:
                        script_lines.append("unfix deform")

                    # Apply new deform fix if strain rate is not zero
                    if abs(strain_rate) > 1e-9:
                        script_lines.append(f"fix deform all deform 1 x erate {strain_rate} remap x")
                    else:
                        script_lines.append("# Relaxation segment (zero strain rate)")

                    script_lines.append(f"run {int(duration)}")
                    script_lines.append("")

            # Bond breakage if enabled
            if fixes_config.get("enable_bond_breakage", False):
                nevery = fixes_config.get("nevery", 1)
                bondtype = fixes_config.get("bondtype", 1)
                rmax = fixes_config.get("rmax", 1.5)
                enable_prob = fixes_config.get("enable_prob", False)
                
                # Build bond break command
                bond_break_cmd = f"fix break_all all bond/break {nevery} {bondtype} {rmax}"
                
                # Add probability if enabled
                if enable_prob:
                    prob_fraction = deform_config.get("prob_fraction", 0.1)
                    prob_seed = deform_config.get("prob_seed", 12345)
                    bond_break_cmd += f" prob {prob_fraction} {prob_seed}"
                
                script_lines.extend([
                    "#------------------------",
                    "# Bond breakage",
                    "#------------------------",
                    bond_break_cmd,
                    ""
                ])
            
            # Output settings
            thermo_output_freq = deform_study.get("thermo_freq", 100)
            trj_output_freq = deform_study.get("thermo_freq", 1000)  # Use same as thermo for simplicity
            
            script_lines.extend([
                "#------------------------",
                "# Output settings",
                "#------------------------"
            ])
            
            # Thermo output
            if output_config.get("enable_thermo", True):
                thermo_style = output_config.get("thermo_style", "step etotal pe ke epair ebond evdwl ecoul elong temp press pxx pyy pzz pxy pxz pyz lx ly lz density")
                script_lines.extend([
                    f"thermo {thermo_output_freq}",
                    f"thermo_style custom {thermo_style}",
                    "thermo_modify lost warn flush yes",
                    ""
                ])
            
            # Stress calculations
            if output_config.get("enable_stress", True):
                script_lines.extend([
                    "# Stress calculations",
                    "compute stress all stress/atom NULL",
                    "compute pstress all reduce sum c_stress[1] c_stress[2] c_stress[3] c_stress[4] c_stress[5] c_stress[6]",
                    ""
                ])
            
            # Custom computes
            if output_config.get("enable_custom_computes", False):
                custom_computes = output_config.get("custom_computes", "")
                if custom_computes:
                    script_lines.extend([
                        "# Custom computes",
                        custom_computes,
                        ""
                    ])
            
            # Trajectory output
            if output_config.get("enable_trajectory", True):
                traj_format = output_config.get("traj_format", "lammpstrj")
                trj_output_items = output_config.get("trj_output_items", "id type x y z fx fy fz")
                
                # Create output directory if it doesn't exist
                output_dir = "output"
                script_lines.extend([
                    f"dump trajectory all custom {trj_output_freq} {output_dir}/{model_name}.{traj_format} {trj_output_items}",
                    ""
                ])
            
            # Custom dumps
            if output_config.get("enable_custom_dumps", False):
                custom_dumps = output_config.get("custom_dumps", "")
                if custom_dumps:
                    script_lines.extend([
                        "# Custom dumps",
                        custom_dumps,
                        ""
                    ])
            
            # Combine all parts
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
            execution_mode = self.config.get("cluster", {}).get("execution_mode", "local")
            
            for study in deform_studies:
                study_name = study.get("name", "study")
                
                for system_file in system_files:
                    system_name = Path(system_file).stem
                    model_name = f"{study_name}_{system_name}"  # Changed to study_name_first
                    
                    # Always use consistent file structure: study/system/model_name.in
                    script_relative_path = f"{study_name}/{system_name}/{model_name}.in"
                    sim_directory = f"{study_name}/{system_name}"
                    
                    if execution_mode == "local":
                        # Local execution - change to simulation directory and run in new terminal
                        if current_os in ['linux', 'darwin']:
                            script_lines.extend([
                                f"echo 'Running simulation: {model_name}'",
                                f"cd {sim_directory}",
                                f"{command_prefix}lmp -in {model_name}.in{command_suffix}",
                                f"echo 'Started simulation in new terminal: {model_name}'",
                                f"cd ../../",  # Go back to root directory
                                ""
                            ])
                        else:  # Windows
                            script_lines.extend([
                                f"echo 'Running simulation: {model_name}'",
                                f"cd {sim_directory}",
                                f"{command_prefix}lmp -in {model_name}.in{command_suffix}",
                                f"echo 'Started simulation in new terminal: {model_name}'",
                                f"cd ../../",  # Go back to root directory
                                ""
                            ])
                    else:
                        # Cluster execution - submit master job file with input file argument
                        if current_os in ['linux', 'darwin']:
                            script_lines.extend([
                                f"echo 'Submitting job: {model_name}'",
                                f"cd {sim_directory}",
                                f"sbatch --job-name=\"{model_name}\" --mail-type=ALL \"../../lammps_simulation.job\" \"{model_name}\"",
                                f"cd ../../",
                                f"echo 'Job submitted: {model_name}'",
                                ""
                            ])
                        else:  # Windows
                            script_lines.extend([
                                f"echo 'Submitting job: {model_name}'",
                                f"cd {sim_directory}",
                                f"sbatch --job-name=\"{model_name}\" --mail-type=ALL \"../../lammps_simulation.job\" \"{model_name}\"",
                                f"cd ../../",
                                f"echo 'Job submitted: {model_name}'",
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
            cluster_config = self.config.get("cluster", {})
            partition = cluster_config.get("cluster_partition", "singlenode")
            nodes = cluster_config.get("cluster_nodes", 1)
            ntasks = cluster_config.get("cluster_ntasks", 72)
            cpus_per_task = cluster_config.get("cluster_cpus_per_task", 1)
            time_limit = cluster_config.get("cluster_time", "24:00:00")
            export_setting = cluster_config.get("cluster_export", "NONE")
            output_file = cluster_config.get("cluster_output", "lammps_output_%j.txt")
            error_file = cluster_config.get("cluster_error", "lammps_error_%j.txt")
            email = cluster_config.get("cluster_mail", "")
            mail_type = cluster_config.get("cluster_mail_type", "ALL")
            
            # Generate master job file that accepts input file as argument
            job_lines = [
                "#!/bin/bash",
                "#SBATCH --job-name=lammps_simulation",
                f"#SBATCH --partition={partition}",
                f"#SBATCH --nodes={nodes}",
                f"#SBATCH --ntasks-per-node={ntasks}",
                f"#SBATCH --cpus-per-task={cpus_per_task}",
                f"#SBATCH --time={time_limit}",
                f"#SBATCH --export={export_setting}",
                f"#SBATCH --output={output_file}",
                f"#SBATCH --error={error_file}"
            ]
            
            # Add email settings if provided
            if email:
                job_lines.extend([
                    f"#SBATCH --mail-user={email}",
                    f"#SBATCH --mail-type={mail_type}"
                ])
            
            job_lines.extend([
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
                "module load lammps",
                "",
                "# Run LAMMPS with input file",
                "srun lmp -in \"$input\"",
                "",
                "echo 'Completed simulation: $MODEL_NAME'",
                ""
            ])
            
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
                    model_name = f"{study_name}_{system_name}"  # Changed to study_name_first
                    
                    # Determine input file path and directory
                    input_file_path = f"{model_name}.in"
                    sim_directory = f"{study_name}/{system_name}"
                    
                    script_lines.extend([
                        f"cd {sim_directory}",
                        f"sbatch --job-name=\"{model_name}\" --mail-type=ALL \"../../lammps_simulation.job\" \"{model_name}\"",
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