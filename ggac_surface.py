#!/usr/bin/env python3
''' ggac_surface.py
Author:     Connor Natzke
Date:       Mar 2021
Revision:   Mar 2021
Purpose:    Generate a Pegasus workflow for OSG submission
'''
# --- Configuration -----------------------------------------------------------
import logging
import os
from Pegasus.api import *
from pathlib import Path

logging.basicConfig(level=logging.DEBUG)

# --- Working Directory Setup -------------------------------------------------
# A good working directory for workflow runs and output files
WORK_DIR = Path.home() / "workflows"
WORK_DIR.mkdir(exist_ok=True)

TOP_DIR = Path(__file__).resolve().parent

# --- Properties --------------------------------------------------------------
props = Properties()
props["pegasus.monitord.encoding"] = "json"

# Provide full kickstart record, including environment, even for successful jobs
props["pegasus.gridstart.arguments"] = "-f"

# Limit number of idle jobs
#props["dagman.maxidle"] = "500"
#props["dagman.maxjobs"] = "500"

# turn off 'register_local' jobs, they are not necesary for my workflow since I don't reuse data.
props["pegasus.register"] = "off"

# Limit the number of transfer jobs so servers don't get overwhelmed
# We need this line for cronos, otherwise it appears as a cyberattack
#props["pegasus.stageout.clusters"] = "1000"
props["dagman.stageout.maxjobs"] = "1"

# Enable more cleanup jobs
#props["pegasus.file.cleanup.clusters.num"] = "2000"

# Set retry limit
props["dagman.retry"] = "3"

# Help Pegasus developers by sharing performance data
props["pegasus.catalog.workflow.amqp.url"] = "amqp://friend:donatedata@msgs.pegasus.isi.edu:5672/prod/workflows"

# Write properties file to ./pegasus.properties
props.write()

# --- Sites -------------------------------------------------------------------
sc = SiteCatalog()

# local site (submit node)
local_site = Site(name="local", arch=Arch.X86_64)

local_shared_scratch = Directory(
    directory_type=Directory.SHARED_SCRATCH, path=WORK_DIR / "scratch")
local_shared_scratch.add_file_servers(FileServer(
    url="file://" + str(WORK_DIR / "scratch"), operation_type=Operation.ALL))
local_site.add_directories(local_shared_scratch)

local_site.add_env(PATH=os.environ["PATH"])
local_site.add_profiles(Namespace.PEGASUS, key='SSH_PRIVATE_KEY',
                        value='/home/cnatzke/.ssh/id_rsa.pegasus')
sc.add_sites(local_site)

# condorpool (execution nodes)
condorpool_site = Site(
    name="condorpool", arch=Arch.X86_64, os_type=OS.LINUX)
condorpool_site.add_pegasus_profile(style="condor")
condorpool_site.add_condor_profile(
    universe="vanilla",
    # requirements="HAS_SINGULARITY == TRUE && OSG_HOST_KERNEL_VERSION >= 31000",
    requirements="HAS_SINGULARITY == TRUE && OSG_HOST_KERNEL_VERSION >= 31000 && GLIDEIN_Site=!=\"SU-ITS\" && GLIDEIN_Site=!=\"Clemson\" && GLIDEIN_Site=!=\"Colorado\"",
    request_cpus=1,
    request_memory="1 GB",
    request_disk="1 GB"
)
sc.add_sites(condorpool_site)

# remote server (for analysis)
remote_site = Site(
    name="remote", arch=Arch.X86_64, os_type=OS.LINUX)

remote_storage = Directory(
    directory_type=Directory.LOCAL_STORAGE, path="/data_fast/cnatzke/OSG_Output")
remote_storage.add_file_servers(FileServer(
    url="scp://cnatzke@cronos.mines.edu/data_fast/cnatzke/OSG_Output", operation_type=Operation.ALL))
remote_site.add_directories(remote_storage)

sc.add_sites(remote_site)

# write SiteCatalog to ./sites.yml
sc.write()

# --- Transformations ---------------------------------------------------------
file_preparation = Transformation(
    name="file_preparation",
    site="local",
    pfn=TOP_DIR / "bin/prepare_files",
    is_stageable=True,
    arch=Arch.X86_64
).add_profiles(Namespace.PEGASUS, key="clusters.size", value=3)

simulation = Transformation(
    name="simulation",
    site="local",
    pfn=TOP_DIR / "bin/run_simulation",
    is_stageable=True,
    arch=Arch.X86_64
)

ntuple = Transformation(
    name="ntuple",
    site="local",
    pfn=TOP_DIR / "bin/run_ntuple",
    is_stageable=True,
    arch=Arch.X86_64
)

merge = Transformation(
    name="merge",
    site="local",
    pfn=TOP_DIR / "bin/merge",
    is_stageable=True,
    arch=Arch.X86_64
)

tc = TransformationCatalog()
tc.add_transformations(file_preparation, simulation, ntuple)
# write TransformationCatalog to ./transformations.yml
tc.write()

# --- Replicas ----------------------------------------------------------------
# Use all input files in "inputs" directory
input_files = [File(f.name) for f in (TOP_DIR / "inputs").iterdir()]

rc = ReplicaCatalog()
for f in input_files:
    rc.add_replica(site="local", lfn=f, pfn=TOP_DIR / "inputs" / f.lfn)

# write ReplicaCatalog to replicas.yml
rc.write()

# --- WorkFlow ----------------------------------------------------------------
jobs = 1025
z_list = ['Z0', 'Z2', 'Z4']
merge_limit = 50

wf = Workflow(name="ggac_surface-workflow")

for z in z_list:
    out_file_name_preparation = f'run_macro_{z}.mac'
    out_file_config = f'simulation_{z}.cfg'
    preparation_job = Job(file_preparation)\
        .add_args('simulation.ini', z, out_file_name_preparation)\
        .add_inputs(File('simulation.ini'))\
        .add_outputs(File(out_file_name_preparation), File(out_file_config))\
        .add_profiles(
            Namespace.CONDOR,
            key="+SingularityImage",
            value='"/cvmfs/singularity.opensciencegrid.org/cnatzke/prepare_files:latest"'
    )

    wf.add_jobs(preparation_job)

    merge_job = None
    merge_id = 0
    merge_count = 0
    
    for job in range(jobs):
        out_file_name_simulation = f'g4out_{z}_{job:04d}.root'
        out_file_name_ntuple = f'Converted_{z}_{job:04d}.root'

        simulation_job = Job(simulation)\
            .add_args(out_file_name_preparation, out_file_name_simulation)\
            .add_inputs(*input_files, File(out_file_name_preparation))\
            .add_outputs(File(out_file_name_simulation), transfer=False)\
            .add_profiles(
                Namespace.CONDOR,
                key="+SingularityImage",
                value='"/cvmfs/singularity.opensciencegrid.org/cnatzke/griffin_simulation:geant4.10.01"'
        )

        ntuple_job = Job(ntuple)\
            .add_args(out_file_name_simulation, out_file_name_ntuple)\
            .add_inputs(File(out_file_name_simulation))\
            .add_outputs(File(out_file_name_ntuple), transfer=False)\
            .add_profiles(
                Namespace.CONDOR,
                key="+SingularityImage",
                value='"/cvmfs/singularity.opensciencegrid.org/cnatzke/ntuple:ggac_surface"')
            # .add_condor_profile(priority="1")

        wf.add_jobs(simulation_job)
        wf.add_jobs(ntuple_job)

        if merge_job is None:
            merge_job = Job(merge)\
                    .add_args(str(merge_id))
                    .add_outputs(File('{}.tar.gz'.format(merge_id)))
        merge_job.add_inputs(File(out_file_name_ntuple))
        if merge_count == merge_limit:
            wf.add_jobs(merge_job)
            merge_job = None
            merge_count = 0

    # do we need to finish the merge job?
    if merge_count > 0:
        wf.add_jobs(merge_job)

# plan workflow
wf.plan(
    dir=WORK_DIR / "runs",
    sites = ["condorpool"],
    output_sites=["remote"],
    submit=True
)
  
