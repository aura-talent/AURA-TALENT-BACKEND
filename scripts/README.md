# Deployment Scripts

This directory contains automation scripts for deploying the Career Ops backend.

## Scripts

### `setup-vm.sh`
**Purpose**: Initial VM configuration (run once)  
**Where**: On the GCP VM (via SSH)  
**When**: After creating a new VM for the first time

**Usage**:
```bash
# Method 1: Copy and run on VM
gcloud compute ssh career-ops-backend --zone=us-central1-a
# Then paste the script contents

# Method 2: Run from local machine
gcloud compute ssh career-ops-backend --zone=us-central1-a < scripts/setup-vm.sh
```

**What it does**:
- Installs system dependencies (git, nginx, etc.)
- Installs uv (Python package manager)
- Clones your repository
- Creates `.env` file template
- Installs Python dependencies
- Sets up systemd service
- Configures nginx reverse proxy
- Starts the service

### `deploy.sh`
**Purpose**: Manual deployment to VM  
**Where**: On your local machine  
**When**: When you want to manually deploy instead of using GitHub Actions

**Usage**:
```bash
./scripts/deploy.sh
```

**What it does**:
- Connects to your GCP VM
- Pulls latest code from git
- Installs/updates dependencies
- Restarts the service
- Runs health check
- Reports deployment status

**Requirements**:
- `gcloud` CLI authenticated
- SSH access to the VM
- Git repository already cloned on VM (setup-vm.sh must have run first)

## Seed / test-data scripts

### `seed_applications_for_job.py`

**Purpose**: Attach real applications to a job so the automation engine has
data to react to, instead of sitting idle at zero applicants.
**Where**: Your local machine (or any box with the backend `.env`)
**When**: You need a job to have applicants — testing phase targets, the
Shortlists page, auto-advance, or the WLC scoring pipeline.

**Usage**:
```bash
.venv/bin/python scripts/seed_applications_for_job.py --job-id <job-id>
```

| Flag | Default | Meaning |
| --- | --- | --- |
| `--job-id` | *required* | The job to attach applications to |
| `--count` | `5` | How many candidates to apply |
| `--skip-evaluation` | off | Create application rows only — skip the LLM scoring pass |

Use `--skip-evaluation` when you only need applicant *counts* (e.g. to trip an
`applicants` phase target). Leave it off when you need real `wlc_score` values —
scores are what the Evaluation phase and the Shortlists page work from.

**Finding a job id**:
```bash
curl -s "http://localhost:8000/employer/jobs?employer_id=<your-user-id>" | python3 -m json.tool
```
Or copy it out of the URL on the job's detail page: `/employer/jobs/<job-id>`.

**What it does**:
- Picks real `role="candidate"` users **that already have a resume on file**,
  skipping anyone already applied to this job
- Creates each application at the job's **first configured stage**
- Runs the real `evaluate_candidate` LangGraph agent per candidate (two chained
  LLM calls, so budget ~5–30s each) unless `--skip-evaluation`

**What it does NOT do** — these are left to the scheduler, exactly as they would
be for a real applicant:
- Headhunter assignment, sourcing, or phase advancement. If the job is in
  `auto` mode the next sweep (every 60s, see `app/employer/scheduler.py`)
  picks it up. In `manual` mode, POST `/employer/jobs/{id}/run` or advance the
  phase yourself.
- Moving anyone past the first stage. Candidates land at "Application
  Received"; move them to "Shortlisted" or later before they appear on the
  Shortlists page.

**Requirements**:
- Backend `.env` present (the script talks to Supabase directly)
- `ANTHROPIC_API_KEY` set unless you pass `--skip-evaluation`
- At least one candidate user with an uploaded resume

**Troubleshooting**:
- *"No job found with id …"* — wrong id, or the job belongs to another employer.
- *"No eligible candidates found"* — every candidate with a resume has already
  applied to this job, or no candidate has uploaded a resume yet. Seed the
  candidate side first (`seed_employer_data.py`).
- *Applications created but no scores* — the WLC pass logs and swallows its own
  errors, so check the server log. A candidate with no resume is skipped by
  design.

> Writes to whatever Supabase project your `.env` points at. There is no
> `--dry-run` and no undo — don't aim it at production.

### `seed_employer_data.py`, `seed_pipeline_automation.py`

Broader fixtures — employer profile, jobs, headhunters, and pipeline/automation
config. Run these first if the workspace is empty, then use
`seed_applications_for_job.py` to load a specific job.

## Permissions

Both deployment scripts are executable:
```bash
chmod +x scripts/setup-vm.sh
chmod +x scripts/deploy.sh
```

## Configuration

These scripts use the following defaults:
- **VM Name**: `career-ops-backend`
- **Zone**: `us-central1-a`
- **App Directory**: `/opt/career-ops-backend`
- **Service Port**: `8000`

To change these, edit the variables at the top of each script.

## Troubleshooting

### setup-vm.sh fails
- Ensure you have SSH access to the VM
- Check that the VM is Ubuntu 22.04 LTS
- Verify you have sudo permissions on the VM

### deploy.sh fails
- Ensure `gcloud` is authenticated: `gcloud auth login`
- Verify the VM name and zone are correct
- Check that setup-vm.sh has been run successfully first
- Verify you have git configured on the VM

## See Also

- `../QUICKSTART-DEPLOY.md` - Complete deployment guide
- `../DEPLOYMENT.md` - Detailed documentation
- `../.github/workflows/deploy.yml` - GitHub Actions workflow
