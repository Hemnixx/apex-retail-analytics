Render deployment guide
======================

This file describes how to deploy the `apex-retail-analytics` detector as a public web service on Render.com.

1) Ensure `submission-small` branch is pushed to GitHub (already done).

2) Sign in to Render and create a new Web Service:
   - Connect your GitHub account and select the repo `Hemnixx/apex-retail-analytics`.
   - Choose branch: `submission-small`.
   - Environment: `Docker` (the repo includes `Dockerfile.detector`).
   - Start Command: `gunicorn -k uvicorn.workers.UvicornWorker app.main:app -b 0.0.0.0:$PORT`
   - Port: `8000` (or leave default $PORT Render provides).

3) Environment variables (optional):
   - `LOG_LEVEL=info`

4) After deploy, Render provides a stable public URL. Use that URL as the `--api-url` when running `pipeline/detect.py` to post events.

Quick test after deploy:

```
curl https://<your-render-url>/health
curl https://<your-render-url>/events
```

If you want, I can open a PR to add this manifest to `main` or push directly — tell me which branch you prefer.
