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
            
            # Get system path and determine if it's single file or directory
            system_path = self.config.get("system", {}).get("system_path", "")
            if not system_path or not os.path.exists(system_path):
                return {"success": False, "message": "System path does not exist."}
            
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
            
            # Check if multi-system processing is enabled
            enable_multi_system = self.config.get("multistudy", {}).get("enable_multi_system", False)
            if is_multi_system and not enable_multi_system:
                return {"success": False, "message": "Multiple .data files found but multi-system processing is not enabled."}
            
            # Create output directory structure
            output_path = self.config.get("output", {}).get("output_path", "")
            if not output_path:
                output_path = os.path.dirname(system_files[0])
            
            # Root simulation folder
            root_simulation_dir = output_path
            os.makedirs(root_simulation_dir, exist_ok=True)
            
            # Create dataFilesFolder and copy all data files there
            data_files_folder = os.path.join(root_simulation_dir, "dataFilesFolder")
            os.makedirs(data_files_folder, exist_ok=True)
            
            # Copy all data files to dataFilesFolder
            data_file_dest_paths = {}
            for i, system_file in enumerate(system_files):
                system_name = Path(system_file).stem
                data_file_dest = os.path.join(data_files_folder, f"{system_name}.data")
                shutil.copy2(system_file, data_file_dest)
                data_file_dest_paths[system_file] = os.path.join("dataFilesFolder", f"{system_name}.data")
                
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
            
            # Check units consistency if multi-system
            if is_multi_system:
                units_check = self.check_units_consistency(system_files)
                if not units_check["consistent"]:
                    return {"success": False, "message": units_check["message"]}
            
            # Generate scripts for each deformation study and system combination
            for study in deform_studies:
                study_name = study.get("name", "study")
                
                # Create deformation study folder
                study_folder = os.path.join(root_simulation_dir, study_name)
                os.makedirs(study_folder, exist_ok=True)
                
                for system_file in system_files:
                    system_name = Path(system_file).stem
                    
                    # Create system-specific folder within study folder
                    system_folder = os.path.join(study_folder, system_name)
                    os.makedirs(system_folder, exist_ok=True)
                    
                    # Generate script for this study-system combination
                    model_name = f"{system_name}_{study_name}"
                    data_file_relative_path = data_file_dest_paths[system_file]
                    
                    result = self.generate_single_script(
                        system_file, model_name, study, 
                        system_folder, data_file_relative_path
                    )
                    
                    if not result["success"]:
                        return result
                    
                    # Generate job file if cluster execution is enabled
                    if self.config.get("cluster", {}).get("execution_mode") == "cluster":
                        job_result = self.generate_job_file(
                            system_file, model_name, result["script_file"], root_simulation_dir, study_name, system_name
                        )
                        if not job_result["success"]:
                            return job_result
            
            # Generate execution script for multi-system
            if is_multi_system and self.config.get("multistudy", {}).get("sequential_execution", True):
                exec_script_result = self.generate_execution_script(root_simulation_dir, system_files, deform_studies)
                if not exec_script_result["success"]:
                    return exec_script_result
            
            return {"success": True, "message": "All scripts generated successfully.", "files": self.generated_files}
            
        except Exception as e:
            return {"success": False, "message": f"Error generating scripts: {str(e)}"}
        
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
            deform_config = self.config.get("deformation", {})
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
                f"read_data {data_file}"
            ])
            
            if system_config.get("use_potential_file", False):
                potential_file = system_config.get("potential_file", "")
                potential_name = Path(potential_file).name
                if os.path.exists(os.path.join(os.path.dirname(data_file), potential_name)):
                    script_lines.append(f"include {potential_name}")
                else:
                    script_lines.append(f"# Warning: Potential file not found: {potential_name}")
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
            
            # Handle wall atoms for wall movement
            method = deform_study.get("method", "fix_deform")
            if method == "wall_movement":
                wall_thickness = system_config.get("wall_thickness", 5.0)
                axis = deform_study.get("axis", "x")
                
                script_lines.extend([
                    "#------------------------",
                    "# Wall atom handling",
                    "#------------------------",
                    f"# Define wall atoms (outer {wall_thickness}% of box in {axis} direction)",
                    f"variable wall_thickness equal {wall_thickness/100.0}",
                    f"variable box_{axis} equal lz",  # This should be the actual box dimension
                    f"variable wall_pos equal v_wall_thickness*v_box_{axis}",
                    f"group wall_atoms region block INF INF INF INF INF INF EDGE EDGE EDGE",
                    f"group mobile_atoms subtract all wall_atoms",
                    "# Exclude wall atoms from integration",
                    "fix integrate mobile_atoms nve",
                    ""
                ])
            
            # Deformation
            deform_params = self.get_deformation_parameters(deform_study, system_config)
            
            if deform_params:
                if method == "fix_deform":
                    script_lines.extend([
                        "#------------------------",
                        "# Deformation",
                        "#------------------------",
                        f"fix deform all deform 1 {deform_params['axis']} {deform_params['style']} {deform_params['rate']} remap x",
                        ""
                    ])
                elif method == "wall_movement":
                    script_lines.extend([
                        "#------------------------",
                        "# Wall movement",
                        "#------------------------"
                    ])
                    
                    # Handle different wall directions
                    direction = deform_params.get('direction', 'positive')
                    if direction == 'symmetric':
                        # Create two walls moving in opposite directions
                        script_lines.extend([
                            "# Symmetric wall movement - both walls moving",
                            f"fix wall_pos all wall/reflect {deform_params['axis']} EDGE {deform_params['velocity']}",
                            f"fix wall_neg all wall/reflect {deform_params['axis']} 0.0 {-deform_params['velocity']}",
                            ""
                        ])
                    else:
                        # Single wall movement
                        edge = "EDGE" if direction == 'positive' else "0.0"
                        script_lines.extend([
                            "# Single wall movement",
                            f"fix wall_move all wall/reflect {deform_params['axis']} {edge} {deform_params['velocity']}",
                            ""
                        ])
            else:
                script_lines.extend([
                    "#------------------------",
                    "# Deformation (skipped - invalid parameters)",
                    "#------------------------",
                    "# Invalid deformation parameters",
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
            
            # Custom computes
            if output_config.get("enable_custom_computes", False):
                custom_computes = output_config.get("custom_computes", "")
                if custom_computes:
                    script_lines.extend([
                        "# Custom computes",
                        custom_computes,
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
            
            # Run simulation
            run_steps = deform_study.get("steps", 10000)
            script_lines.extend([
                "#------------------------",
                "# Run simulation",
                "#------------------------",
                f"run {run_steps}"
            ])
            
            # Combine all parts
            full_script = "\n".join(script_lines)
            
            return full_script
            
        except Exception as e:
            return f"# Error generating script content: {str(e)}"
        
    def get_deformation_parameters(self, deform_study, system_config):
        """Get deformation parameters based on study configuration"""
        method = deform_study.get("method", "fix_deform")
        axis = deform_study.get("axis", "x")
        style_dir = deform_study.get("style_dir", "final")
        steps = deform_study.get("steps", 10000)
        
        use_strain_rate = self.config.get("multistudy", {}).get("use_strain_rate", True)
        rate_strain = deform_study.get("rate_strain", 0.001)
        
        if method == "fix_deform":
            if use_strain_rate:
                # Use strain rate directly
                return {
                    'rate': rate_strain,
                    'axis': axis,
                    'style': style_dir
                }
            else:
                # Use engineering strain - calculate equivalent rate
                # For engineering strain: rate = strain / time
                timestep = system_config.get("timestep", 0.001)
                time = steps * timestep
                
                if time > 0:
                    rate = rate_strain / time
                else:
                    rate = 0.001
                    
                return {
                    'rate': rate,
                    'axis': axis,
                    'style': style_dir
                }
                    
        elif method == "wall_movement":
            if use_strain_rate:
                # Use wall velocity directly
                return {
                    'velocity': rate_strain,
                    'axis': axis,
                    'direction': style_dir
                }
            else:
                # Use engineering strain - calculate equivalent velocity
                # For wall movement: velocity = (strain * box_length) / time
                # We need to estimate box length - this is simplified
                estimated_box_length = 100.0  # Default estimate
                timestep = system_config.get("timestep", 0.001)
                time = steps * timestep
                
                if time > 0:
                    velocity = (rate_strain * estimated_box_length) / time
                else:
                    velocity = 0.01
                    
                return {
                    'velocity': velocity,
                    'axis': axis,
                    'direction': style_dir
                }
        
        return None
        
    def generate_job_file(self, data_file, model_name, script_filename, root_simulation_dir, study_name, system_name):
        """Generate a cluster job submission file"""
        try:
            cluster_config = self.config.get("cluster", {})
            
            # Get cluster settings
            partition = cluster_config.get("cluster_partition", "singlenode")
            nodes = cluster_config.get("cluster_nodes", 1)
            ntasks = cluster_config.get("cluster_ntasks", 72)
            time_limit = cluster_config.get("cluster_time", "24:00:00")
            email = cluster_config.get("cluster_mail", "")
            
            # Generate job filename in root simulation directory
            job_filename = os.path.join(root_simulation_dir, f"{model_name}.job")
            
            # Calculate relative path to script file
            script_relative_path = os.path.join(study_name, system_name, f"{model_name}.in")
            
            # Generate job file content
            job_lines = [
                "#!/bin/bash",
                f"#SBATCH --job-name={model_name}",
                f"#SBATCH --partition={partition}",
                f"#SBATCH --nodes={nodes}",
                f"#SBATCH --ntasks={ntasks}",
                f"#SBATCH --time={time_limit}",
            ]
            
            if email:
                job_lines.extend([
                    f"#SBATCH --mail-type=ALL",
                    f"#SBATCH --mail-user={email}",
                ])
            
            job_lines.extend([
                "",
                "# Load modules",
                "module load lammps",
                "",
                "# Change to the correct directory",
                f"cd {root_simulation_dir}",
                "",
                "# Run LAMMPS",
                f"srun lmp -in {script_relative_path}",
                ""
            ])
            
            # Write job file
            with open(job_filename, 'w') as f:
                f.write("\n".join(job_lines))
            
            self.generated_files.append(job_filename)
            
            return {"success": True, "message": f"Job file generated: {job_filename}"}
            
        except Exception as e:
            return {"success": False, "message": f"Error generating job file: {str(e)}"}
        
    def generate_execution_script(self, root_simulation_dir, system_files, deform_studies):
        """Generate execution script for sequential multi-system processing"""
        try:
            exec_script_path = os.path.join(root_simulation_dir, "run_all.sh")
            
            script_lines = [
                "#!/bin/bash",
                "# Sequential execution script for multiple LAMMPS simulations",
                "",
                "echo \"Starting sequential LAMMPS simulations...\"",
                ""
            ]
            
            # Get execution mode
            execution_mode = self.config.get("cluster", {}).get("execution_mode", "local")
            
            for study in deform_studies:
                study_name = study.get("name", "study")
                
                for system_file in system_files:
                    system_name = Path(system_file).stem
                    model_name = f"{system_name}_{study_name}"
                    
                    # Calculate relative path to script file
                    script_relative_path = os.path.join(study_name, system_name, f"{model_name}.in")
                    
                    if execution_mode == "local":
                        # Local execution
                        script_lines.extend([
                            f"echo \"Running simulation: {model_name}\"",
                            f"cd {root_simulation_dir}",
                            f"lmp -in {script_relative_path}",
                            "echo \"Completed: {model_name}\"",
                            ""
                        ])
                    else:
                        # Cluster execution
                        job_filename = os.path.join(root_simulation_dir, f"{model_name}.job")
                        script_lines.extend([
                            f"echo \"Submitting job: {model_name}\"",
                            f"cd {root_simulation_dir}",
                            f"sbatch {job_filename}",
                            "echo \"Job submitted: {model_name}\"",
                            ""
                        ])
            
            script_lines.extend([
                "echo \"All simulations completed!\"",
                ""
            ])
            
            # Write execution script
            with open(exec_script_path, 'w') as f:
                f.write("\n".join(script_lines))
            
            # Make script executable
            os.chmod(exec_script_path, 0o755)
            
            self.generated_files.append(exec_script_path)
            
            return {"success": True, "message": f"Execution script generated: {exec_script_path}"}
            
        except Exception as e:
            return {"success": False, "message": f"Error generating execution script: {str(e)}"}
        
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