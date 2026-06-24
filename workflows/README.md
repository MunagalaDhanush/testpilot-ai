# n8n Workflow Setup

## Overview
The n8n workflow bridges GitHub webhooks and the TestPilot AI backend. It:
1. Receives PR open/synchronize events from GitHub
2. Forwards the payload to `POST /webhook/github`
3. Polls `GET /jobs/{job_id}` until the job completes
4. Posts a summary comment back to the GitHub PR

## Prerequisites
- n8n instance running (self-hosted or cloud)
- `GITHUB_TOKEN` with `repo` scope
- TestPilot AI backend accessible at a reachable URL

## Local Setup with Docker

Add this to `docker-compose.yml` if you want n8n locally:

```yaml
n8n:
  image: n8nio/n8n:1.70.3
  ports:
    - "5678:5678"
  environment:
    N8N_BASIC_AUTH_ACTIVE: "true"
    N8N_BASIC_AUTH_USER: admin
    N8N_BASIC_AUTH_PASSWORD: changeme
    WEBHOOK_URL: http://localhost:5678
  volumes:
    - n8n-data:/home/node/.n8n
```

## Workflow Nodes

### Node 1: GitHub Webhook Trigger
- Type: Webhook
- Path: `/github-pr`
- Method: POST
- Authentication: Header Auth (`X-Hub-Signature-256`)

### Node 2: Forward to TestPilot
- Type: HTTP Request
- URL: `http://api:8000/webhook/github`
- Method: POST
- Body: `={{ $json }}`
- Headers: forward all original headers (including `X-Hub-Signature-256`)

### Node 3: Extract job_id
- Type: Set
- `job_id` = `={{ $json.job_id }}`

### Node 4: Poll Job Status (Wait + Loop)
- Type: Wait (5 seconds)
- Then: HTTP Request to `http://api:8000/jobs/{{ $json.job_id }}`
- Loop back until `status` is `completed` or `failed`

### Node 5: Post GitHub Comment
- Type: GitHub (Post Comment)
- Repository: from webhook payload `repository.full_name`
- Issue Number: from webhook payload `pull_request.number`
- Body: formatted summary from `final_summary`

## GitHub Webhook Configuration
1. Go to your repo → Settings → Webhooks → Add webhook
2. Payload URL: `https://<your-n8n-host>/webhook/github-pr`
3. Content type: `application/json`
4. Secret: same value as `GITHUB_WEBHOOK_SECRET` in your `.env`
5. Events: "Pull requests" only

## Environment Variables Required in n8n
- `GITHUB_TOKEN` — for posting comments
- TestPilot backend URL if not using Docker networking
