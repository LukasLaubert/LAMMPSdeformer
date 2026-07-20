#!/usr/bin/env python3
"""
LAMMPS Script Generator - Enhanced Version

Handles the generation of LAMMPS input scripts and cluster job files
based on user configuration with support for symmetric wall movement,
engineering strain, and proper units handling.
"""

import os
import json
import glob
import subprocess
import tempfile
import math
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
            
            # Check if multi-system processing is enabled
            if self.config.get("multisystem", {}).get("enable_multi_system", False):
                # Process multiple systems
                system_files = self.get_system_files()
                
                if not system_files:
                    return {"success": False, "message": "No system files found."}
                    
                # Check units consistency
                units_check = self.check_units_consistency(system_files)
                if not units_check["consistent"]:
                    return {"success": False, "message": units_check["message"]}
                    
                # Check if multi-deformation is enabled
                if self.config.get("multistudy", {}).get("enable_multi_deform", False):
                    # Process multiple deformation studies for each system
                    deform_studies = self.config.get("multistudy", {}).get("deform_studies", [])
                    
                    if not deform_studies:
                        return {"success": False, "message": "No deformation studies defined."}
                        
                    for system_file in system_files:
                        for study in deform_studies:
                            result = self.generate_single_script(system_file, study)
                            if not result["success"]:
                                return result
                else:
                    # Process single deformation for each system
                    for system_file in system_files:
                        result = self.generate_single_script(system_file)
                        if not result["success"]:
                            return result
            else:
                # Process single system
                data_file = self.config.get("system", {}).get("data_file", "")
                
                if not data_file or not os.path.exists(data_file):
                    return {"success": False, "message": "Data file not found."}
                    
                # Check if multi-deformation is enabled
                if self.config.get("multistudy", {}).get("enable_multi_deform", False):
                    # Process multiple deformation studies
                    deform_studies = self.config.get("multistudy", {}).get("deform_studies", [])
                    
                    if not deform_studies:
                        return {"success": False, "message": "No deformation studies defined."}
                        
                    for study in deform_studies:
                        result = self.generate_single_script(data_file, study)
                        if not result["success"]:
                            return result
                else:
                    # Process single deformation
                    result = self.generate_single_script(data_file)
                    if not result["success"]:
                        return result
                        
            return {"success": True, "message": "All scripts generated successfully.", "files": self.generated_files}
            
        except Exception as e:
            return {"success": False, "message": f"Error generating scripts: {str(e)}"}
        
    def get_system_files(self):
        """Get list of system files based on configuration"""
        system_path = self.config.get("multisystem", {}).get("multi_system_path", "")
        pattern = self.config.get("multisystem", {}).get("multi_system_pattern", "*.data")
        
        if not system_path:
            return []
            
        search_pattern = os.path.join(system_path, pattern)
        return glob.glob(search_pattern)
        
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
        
    def generate_single_script(self, data_file, deform_study=None):
        """Generate a single LAMMPS input script"""
        try:
            # Create output directory if it doesn't exist
            output_path = self.config.get("output", {}).get("output_path", "")
            if not output_path:
                output_path = os.path.dirname(data_file)
                
            os.makedirs(output_path, exist_ok=True)
            
            # Generate model name
            model_name = self.config.get("output", {}).get("model_name", "model")
            if deform_study:
                study_name = deform_study.get("name", "study")
                model_name = f"{model_name}_{study_name}"
                
            # Generate script filename
            script_filename = os.path.join(output_path, f"{model_name}.in")
            
            # Generate the script content
            script_content = self.generate_script_content(data_file, model_name, deform_study)
            
            # Write the script to file
            try:
                with open(script_filename, 'w') as f:
                    f.write(script_content)
                self.generated_files.append(script_filename)
            except Exception as e:
                return {"success": False, "message": f"Failed to write script file: {str(e)}"}
                
            # Generate job file if cluster execution is enabled
            if self.config.get("cluster", {}).get("execution_mode") == "cluster":
                job_filename = os.path.join(output_path, f"{model_name}.job")
                job_content = self.generate_job_file(data_file, model_name, script_filename)
                
                try:
                    with open(job_filename, 'w') as f:
                        f.write(job_content)
                    self.generated_files.append(job_filename)
                except Exception as e:
                    return {"success": False, "message": f"Failed to write job file: {str(e)}"}
                
            return {"success": True, "message": f"Script generated: {script_filename}"}
            
        except Exception as e:
            return {"success": False, "message": f"Error generating script: {str(e)}"}
        
    def generate_script_content(self, data_file, model_name, deform_study=None):
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
                if os.path.exists(potential_file):
                    script_lines.append(f"include {potential_file}")
                else:
                    script_lines.append(f"# Warning: Potential file not found: {potential_file}")
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
            initial_velocity_seed = system_config.get("initial_velocity_seed", 12345)
            
            script_lines.extend([
                "#------------------------",
                "# Ensemble settings",
                "#------------------------"
            ])
            
            # Initial velocity
            script_lines.extend([
                "# Initial velocity",
                f"velocity all create {temp_init} {initial_velocity_seed} dist gaussian loop geom",
                ""
            ])
            
            # Timestep with units conversion
            timestep = system_config.get("timestep", 0.001)
            timestep_units = system_config.get("timestep_units", "ps")
            
            # Convert timestep based on units
            timestep = self.convert_timestep(timestep, timestep_units, units)
            
            script_lines.extend([
                "# Timestep",
                f"timestep {timestep}",
                ""
            ])
            
            # Ensemble-specific fixes
            if ensemble == "NVT":
                script_lines.extend([
                    "# NVT ensemble",
                    f"fix nvt all nvt temp {temp_init} {temp_end} 0.1",
                    ""
                ])
            elif ensemble == "NPT":
                pressure = system_config.get("pressure", 1.0)
                script_lines.extend([
                    "# NPT ensemble",
                    f"fix npt all npt temp {temp_init} {temp_end} 0.1 iso {pressure} {pressure} 1.0",
                    ""
                ])
            
            # Handle wall atoms exclusion for wall movement
            if deform_config.get("method") == "wall_movement":
                script_lines.extend([
                    "#------------------------",
                    "# Wall atom handling",
                    "#------------------------",
                    "# Exclude wall atoms from integration",
                    "group wall_atoms type 2",  # Assuming type 2 is wall atoms
                    "group mobile_atoms subtract all wall_atoms",
                    "fix integrate mobile_atoms nve",
                    ""
                ])
            
            # Deformation
            if deform_config.get("method") == "fix_deform":
                deform_params = self.get_deform_parameters(deform_config, deform_study)
                
                if deform_params:
                    script_lines.extend([
                        "#------------------------",
                        "# Deformation",
                        "#------------------------",
                        f"fix deform all deform 1 {deform_params['axis']} {deform_params['style']} {deform_params['rate']} remap x",
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
            else:
                # Wall movement
                wall_params = self.get_wall_parameters(deform_config, deform_study)
                
                if wall_params:
                    script_lines.extend([
                        "#------------------------",
                        "# Wall movement",
                        "#------------------------"
                    ])
                    
                    # Handle symmetric wall movement
                    if wall_params['direction'] == 'symmetric':
                        # Create two walls moving in opposite directions
                        script_lines.extend([
                            "# Symmetric wall movement - both walls moving",
                            f"fix wall_pos all wall/reflect {wall_params['axis']} EDGE {wall_params['velocity']}",
                            f"fix wall_neg all wall/reflect {wall_params['axis']} 0.0 {-wall_params['velocity']}",
                            ""
                        ])
                    else:
                        # Single wall movement
                        edge = "EDGE" if wall_params['direction'] == 'positive' else "0.0"
                        script_lines.extend([
                            "# Single wall movement",
                            f"fix wall_move all wall/reflect {wall_params['axis']} {edge} {wall_params['velocity']}",
                            ""
                        ])
                else:
                    script_lines.extend([
                        "#------------------------",
                        "# Wall movement (skipped - invalid parameters)",
                        "#------------------------",
                        "# Invalid wall parameters",
                        ""
                    ])
            
            # Output settings
            thermo_output_freq = deform_config.get("thermo_output_freq", 100)
            trj_output_freq = deform_config.get("trj_output_freq", 1000)
            
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
                output_dir = os.path.join(os.path.dirname(data_file), "output")
                os.makedirs(output_dir, exist_ok=True)
                
                script_lines.extend([
                    f"dump trajectory all custom {trj_output_freq} output/{model_name}.{traj_format} {trj_output_items}",
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
            run_steps = deform_config.get("run_steps", 10000)
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
        
    def convert_timestep(self, timestep, timestep_units, system_units):
        """Convert timestep based on units"""
        # If units match, no conversion needed
        if timestep_units == system_units:
            return timestep
            
        # Conversion factors to base units (seconds)
        to_seconds = {
            'fs': 1e-15,
            'ps': 1e-12,
            'ns': 1e-9,
            's': 1.0
        }
        
        # Convert input to seconds
        if timestep_units in to_seconds:
            timestep_seconds = timestep * to_seconds[timestep_units]
        else:
            return timestep  # Unknown units, return as-is
            
        # Convert from seconds to target units
        if system_units in to_seconds:
            return timestep_seconds / to_seconds[system_units]
        else:
            return timestep  # Unknown target units, return as-is
            
    def get_deform_parameters(self, deform_config, deform_study=None):
        """Get deformation parameters based on configuration"""
        if deform_config.get("use_strain_rate", True):
            # Use strain rate
            if deform_study:
                rate = float(deform_study.get("rate", 0.001))
                axis = deform_study.get("axis", "x")
                style = deform_study.get("style", "final")
            else:
                rate = deform_config.get("deform_rate", 0.001)
                axis = deform_config.get("deform_axis", "x")
                style = deform_config.get("deform_style", "final")
                
            return {
                'rate': rate,
                'axis': axis,
                'style': style
            }
        else:
            # Use engineering strain - calculate equivalent rate
            if deform_study:
                engineering_strain = float(deform_study.get("engineering_strain", 0.1))
                max_strain = float(deform_study.get("max_strain", 0.5))
                axis = deform_study.get("axis", "x")
                style = deform_study.get("style", "final")
                steps = int(deform_study.get("steps", 10000))
            else:
                engineering_strain = deform_config.get("engineering_strain", 0.1)
                max_strain = deform_config.get("max_strain", 0.5)
                axis = deform_config.get("deform_axis", "x")
                style = deform_config.get("deform_style", "final")
                steps = deform_config.get("run_steps", 10000)
            
            # Calculate equivalent strain rate
            # For engineering strain: rate = strain / time
            # Time = steps * timestep
            timestep = deform_config.get("run_steps", 10000)  # This will be converted later
            time = steps * timestep
            
            if time > 0:
                rate = engineering_strain / time
            else:
                rate = 0.001
                
            return {
                'rate': rate,
                'axis': axis,
                'style': style
            }
            
    def get_wall_parameters(self, deform_config, deform_study=None):
        """Get wall movement parameters based on configuration"""
        if deform_config.get("use_strain_rate", True):
            # Use wall velocity
            if deform_study:
                velocity = float(deform_study.get("rate", 0.01))
                axis = deform_study.get("axis", "x")
                direction = deform_study.get("style", "positive")  # Using style field for direction
            else:
                velocity = deform_config.get("wall_velocity", 0.01)
                axis = deform_config.get("wall_axis", "x")
                direction = deform_config.get("wall_direction", "positive")
                
            return {
                'velocity': velocity,
                'axis': axis,
                'direction': direction
            }
        else:
            # Use engineering strain - calculate equivalent velocity
            if deform_study:
                engineering_strain = float(deform_study.get("engineering_strain", 0.1))
                max_strain = float(deform_study.get("max_strain", 0.5))
                axis = deform_study.get("axis", "x")
                direction = deform_study.get("style", "positive")
                steps = int(deform_study.get("steps", 10000))
            else:
                engineering_strain = deform_config.get("wall_engineering_strain", 0.1)
                max_strain = deform_config.get("wall_max_strain", 0.5)
                axis = deform_config.get("wall_axis", "x")
                direction = deform_config.get("wall_direction", "positive")
                steps = deform_config.get("run_steps", 10000)
            
            # Calculate equivalent wall velocity
            # For wall movement: velocity = (strain * box_length) / time
            # We need to estimate box length from data file or use a default
            # This is a simplified calculation - in practice, you'd read box dimensions
            estimated_box_length = 100.0  # Default estimate
            time = steps * deform_config.get("run_steps", 10000) * 0.001  # Rough estimate
            
            if time > 0:
                velocity = (engineering_strain * estimated_box_length) / time
            else:
                velocity = 0.01
                
            return {
                'velocity': velocity,
                'axis': axis,
                'direction': direction
            }
        
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
        
    def generate_job_file(self, data_file, model_name, script_filename):
        """Generate a cluster job submission file"""
        try:
            cluster_config = self.config.get("cluster", {})
            
            # Get cluster settings
            partition = cluster_config.get("cluster_partition", "singlenode")
            nodes = cluster_config.get("cluster_nodes", 1)
            ntasks = cluster_config.get("cluster_ntasks", 72)
            time_limit = cluster_config.get("cluster_time", "24:00:00")
            email = cluster_config.get("cluster_mail", "")
            
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
                job_lines.append(f"#SBATCH --mail-type=ALL")
                job_lines.append(f"#SBATCH --mail-user={email}")
            
            job_lines.extend([
                "",
                "# Load modules",
                "module load lammps",
                "",
                "# Run LAMMPS",
                f"srun lammps -in {script_filename}",
                ""
            ])
            
            return "\n".join(job_lines)
            
        except Exception as e:
            return f"# Error generating job file: {str(e)}"