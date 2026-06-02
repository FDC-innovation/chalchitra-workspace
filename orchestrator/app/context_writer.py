import os
from datetime import datetime

VOLUMES = "/app/shared/volumes"

def write_context(episode_id: str, node: str, data: dict):
    episode_dir = os.path.join(VOLUMES, episode_id)
    os.makedirs(episode_dir, exist_ok=True)
    context_path = os.path.join(episode_dir, "context.md")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(context_path, "a", encoding="utf-8") as f:
        f.write(f"\n---\n## [{timestamp}] Node: {node.upper()}\n\n")
        for key, value in data.items():
            if isinstance(value, list):
                f.write(f"**{key}:** {len(value)} items\n")
                for i, item in enumerate(value[:3]):
                    f.write(f"  - {item}\n")
                if len(value) > 3:
                    f.write(f"  - ... and {len(value)-3} more\n")
            elif isinstance(value, str) and len(value) > 200:
                f.write(f"**{key}:**\n```\n{value[:500]}...\n```\n")
            else:
                f.write(f"**{key}:** {value}\n")
        f.write("\n")
