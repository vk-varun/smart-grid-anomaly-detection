@echo off
echo ====================================================
echo Running Controlled Comparative Experiment
echo (Cloud-Only Baseline vs. Edge-Fog-Cloud Distributed)
echo ====================================================
python experiments/run_experiment.py --architecture both --meters 50 --duration 60 --seed 42 --plot
pause
