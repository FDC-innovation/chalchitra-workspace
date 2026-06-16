Chalchitra — Local AI Podcast Pipeline
Pull and run the podcast pipeline locally:
bash# 1. Clone and switch to branch
git clone https://github.com/FDC-innovation/chalchitra-workspace.git
cd chalchitra-workspace
git checkout podcast-local-ai-pipeline
git pull origin podcast-local-ai-pipeline
bash# 2. Install Ollama and pull model
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.2
bash# 3. Make Ollama accessible to Docker
sudo systemctl edit ollama
# Add these two lines in the editor:
# [Service]
# Environment="OLLAMA_HOST=0.0.0.0"

sudo systemctl daemon-reload
sudo systemctl restart ollama
bash# 4. Setup env
cp .env.example .env
# Fill in your keys in .env
bash# 5. Build and start all services
docker compose build
docker compose up -d
docker compose ps
bash# 6. Find your Docker gateway IP and set it in .env
docker network inspect chalchitra-workspace_chalchitra | grep Gateway
# Add to .env:  OLLAMA_URL=http://<gateway-ip>:11434
bash# 7. Run the pipeline
chmod +x run_podcast.sh
./run_podcast.sh /path/to/your_video.mp4
bash# 8. Monitor
tail -f shared/volumes/pipeline.log
bash# 9. Get output
find shared/volumes -name "podcast_final.mp4"

Share this with your team and they should be up and running! 🚀