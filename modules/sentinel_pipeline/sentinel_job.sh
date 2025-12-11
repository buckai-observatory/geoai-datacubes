#!/bin/bash
#SBATCH --job-name=sentinel_pipeline
#SBATCH --output=sentinel_output.log
#SBATCH --error=sentinel_error.log
#SBATCH --time=04:00:00
#SBATCH --mem=8G
#SBATCH --cpus-per-task=4
#SBATCH --mail-type=END,FAIL
#SBATCH --mail-user=jain.894@osu.edu

# Load Anaconda module
module load python/anaconda3-2024.10

# Initialize Conda (important on Unity)
eval "$(conda shell.bash hook)"
conda activate sentinel_env

# Go to your project folder
cd ~/sentinel_pipeline

# Run the pipeline
python main.py
