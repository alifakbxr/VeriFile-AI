import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

from colab_mcp.websocket_server import ColabWebSocketServer
from colab_mcp.session import ColabTransport
from fastmcp import Client

NOTEBOOK_PATH = Path("notebooks/VeriFile_HackDay_Colab.ipynb")
DRIVE_ID = "1E6wv2ft5EXBq4_SfTgF3OFXdP93Fhj6A"
COLAB_URL = f"https://colab.research.google.com/drive/{DRIVE_ID}"

async def main():
    with open(NOTEBOOK_PATH, "r", encoding="utf-8") as f:
        nb_data = json.load(f)

    target_cells = nb_data.get("cells", [])
    print(f"Loaded {len(target_cells)} cells from {NOTEBOOK_PATH}")

    wss = ColabWebSocketServer()
    async with wss:
        token = wss.token
        port = wss.port
        full_url = f"{COLAB_URL}#mcpProxyToken={token}&mcpProxyPort={port}"
        print(f"\n[1] Membuka tab Colab untuk notebook drive {DRIVE_ID}...")
        print(f"URL: {full_url}\n")

        # Open in default browser
        subprocess.Popen(["xdg-open", full_url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        print("[2] Menunggu koneksi WebSocket dari tab Google Colab (maksimal 60 detik)...")
        try:
            await asyncio.wait_for(wss.connection_live.wait(), timeout=60.0)
        except asyncio.TimeoutError:
            print("❌ Timeout: Tab Colab belum terhubung. Pastikan browser membuka URL dan terhubung ke localhost.")
            return

        print("✅ Terhubung ke Google Colab!")
        transport = ColabTransport(wss)
        async with Client(transport) as client:
            # 1. Get current cells in the drive notebook
            res = await client.call_tool("get_cells", {})
            current = json.loads(res.content[0].text)
            curr_cells = current.get("cells", [])
            print(f"Notebook saat ini memiliki {len(curr_cells)} sel.")

            # 2. Delete all existing cells except the first one (Colab needs at least 1 cell)
            for c in curr_cells[1:]:
                cid = c.get("id")
                try:
                    await client.call_tool("delete_cell", {"cellId": cid})
                except Exception as e:
                    print(f"Gagal hapus sel {cid}: {e}")

            # 3. Update the first cell with target cell 0
            if target_cells and curr_cells:
                first_target = target_cells[0]
                first_src = "".join(first_target.get("source", []))
                first_id = curr_cells[0].get("id")
                await client.call_tool("update_cell", {"cellId": first_id, "content": first_src})
                print("Sel 0 diperbarui.")

            # 4. Insert the rest of target cells
            for idx, c in enumerate(target_cells[1:], start=1):
                ctype = c.get("cell_type")
                csrc = "".join(c.get("source", []))
                if ctype == "code":
                    await client.call_tool("add_code_cell", {"cellIndex": idx, "code": csrc, "language": "python"})
                else:
                    await client.call_tool("add_text_cell", {"cellIndex": idx, "content": csrc})
                print(f"Sel {idx} ({ctype}) ditambahkan.")

            print("\n🎉 Berhasil menyinkronkan seluruh sel notebook ke Google Colab!")

if __name__ == "__main__":
    asyncio.run(main())

