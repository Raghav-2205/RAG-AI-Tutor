# Production Deployment Guide

This guide matches the current repo layout:

- FastAPI serves both the frontend and `/api`
- MongoDB runs as a separate container
- ChromaDB runs as a separate container
- Runtime configuration comes from `.env`
- `WinSCP` uploads files, but `SSH` does the actual install and deployment work

## 1. What WinSCP Can and Cannot Do

Use `WinSCP` for:

- uploading the repo to the server
- editing `.env` on the server
- downloading backups and logs when needed

Do not use `WinSCP` for:

- installing Docker
- installing Nginx or Certbot
- installing MongoDB manually
- installing Python packages inside the app container
- starting or restarting the production stack

Those steps must be done over `SSH`.

## 2. Server Requirements

- Ubuntu 22.04 or 24.04
- A domain name pointed to the VPS public IP
- Firewall/security group open for ports `22`, `80`, and `443`
- SSH access with sudo privileges

## 3. Install Server Software Over SSH

SSH into the VPS and run:

```bash
sudo apt update
sudo apt install -y ca-certificates curl gnupg nginx certbot python3-certbot-nginx

sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo \"$VERSION_CODENAME\") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker $USER
```

Log out and back in so the Docker group change applies.

## 4. Upload the Repo with WinSCP

Upload the project to a server directory such as:

```text
/opt/rag-lms
```

Do not upload these local-only paths:

- `venv/`
- `venv312/`
- `.git/`
- `__pycache__/`
- `pytest-cache-files-*`
- `logs/`
- `tmp/`
- `.tmp-py/`

Upload the source, `Dockerfile`, `docker-compose.prod.yml`, `.env.production.example`, and `deployment/docker/nginx.conf`.

## 5. Create the Production .env on the Server

On the server:

```bash
cd /opt/rag-lms
cp .env.production.example .env
nano .env
```

Set these values at minimum:

```ini
API_HOST=0.0.0.0
RUN_PORT=8000
MONGODB_URI=mongodb://mongodb:27017
DATABASE_NAME=rag_ai_tutor_prod
CHROMA_API_URL=http://chroma:8000/api/v2
CHROMA_TENANT=default_tenant
CHROMA_DATABASE=default_database
GEMINI_API_KEY=your_real_key
JWT_SECRET_KEY=replace-with-a-long-random-secret
SECRET_KEY=replace-with-a-long-random-secret
ALLOWED_ORIGINS=https://yourdomain.com
UPLOAD_DIR=/app/uploads
```

Important:

- `config/production.yaml` is not the production source of truth right now.
- The app reads environment variables from `.env`.
- `JWT_SECRET_KEY` is the auth secret the backend actually uses.

## 6. Start the Containers

From the repo root on the server:

```bash
cd /opt/rag-lms
mkdir -p uploads
docker compose -f docker-compose.prod.yml up -d --build
docker ps
docker logs rag-lms-web --tail 100
```

This stack starts:

- `web`
- `mongodb`
- `chroma`

## 7. Configure Nginx

Copy the provided Nginx config into place:

```bash
sudo cp deployment/docker/nginx.conf /etc/nginx/sites-available/rag-lms
sudo nano /etc/nginx/sites-available/rag-lms
```

Replace:

- `yourdomain.com`
- `www.yourdomain.com`

Enable the site:

```bash
sudo ln -sf /etc/nginx/sites-available/rag-lms /etc/nginx/sites-enabled/rag-lms
sudo nginx -t
sudo systemctl reload nginx
```

At this stage, HTTP should proxy to the app on `127.0.0.1:8000`.

## 8. Enable HTTPS with Certbot

After the domain resolves to the VPS and HTTP works:

```bash
sudo certbot --nginx -d yourdomain.com -d www.yourdomain.com
```

Choose the redirect option when Certbot asks. That makes Nginx force HTTPS.

## 9. Verify the Deployment

Run these checks:

```bash
curl -I http://yourdomain.com
curl -I https://yourdomain.com
curl https://yourdomain.com/health
docker ps
docker logs rag-lms-web --tail 100
```

Then test in the browser:

- register and log in
- upload a PDF
- ask a RAG question
- open a citation
- load teacher LMS pages
- load student LMS pages

Finally restart the app once:

```bash
docker compose -f docker-compose.prod.yml restart
```

Confirm that:

- uploads still exist
- MongoDB data still exists
- Chroma vectors still exist

## 10. Updating the Server Later

When you change code locally:

1. Upload the changed files with WinSCP, or pull the latest commit over SSH.
2. Rebuild and restart:

```bash
cd /opt/rag-lms
docker compose -f docker-compose.prod.yml up -d --build
```

Useful logs:

```bash
docker logs rag-lms-web --tail 200
docker logs rag-lms-mongodb --tail 200
docker logs rag-lms-chroma --tail 200
sudo tail -n 200 /var/log/nginx/error.log
sudo tail -n 200 /var/log/nginx/access.log
```

## 11. Backup Targets

Back up these three things:

- MongoDB data in the `mongodb_data` Docker volume
- Chroma data in the `chroma_data` Docker volume
- uploaded files in `/opt/rag-lms/uploads`

## Notes and Current Risks

- The production stack should use `docker-compose.prod.yml`, not the older dev-focused compose file.
- The backend now honors `ALLOWED_ORIGINS` instead of forcing `*`.
- The Docker image no longer bakes `.env` into the container.
- The image now includes `data/base_dataset` so startup auto-indexing still works in production.
- The first retrieval request may download Hugging Face models if they are not already cached in the container or reachable from the server network.
