import json
import subprocess

raw = subprocess.check_output(['git', 'show', 'HEAD:notebooks/VeriFile_HackDay_Colab.ipynb']).decode('utf-8')
nb = json.loads(raw)

nb['cells'][8]['source'] = [
    "## 4. (Opsional) Aktifkan Gemma 4 Multimodal (GPU) dan/atau Fallback Gemini API (tanpa GPU)\n",
    "\n",
    "- **Utama (GPU):** Model default `google/gemma-4-E2B-it` membutuhkan *T4 GPU* dan akses Hugging Face.\n",
    "- **Fallback Otomatis (CPU/GPU):** Simpan `GEMINI_API_KEY` di Colab **Secrets** (ikon kunci di panel kiri). Bila GPU tidak tersedia atau Gemma lokal gagal dimuat, sistem otomatis beralih ke **Gemini API** (`gemini-2.5-flash`) tanpa perlu GPU."
]

nb['cells'][9]['source'] = [
    "# 1) Konfigurasi fallback Gemini API dari Colab Secrets (berjalan di CPU maupun GPU).\n",
    "has_gemini_fallback = False\n",
    "try:\n",
    "    from google.colab import userdata\n",
    "    gemini_key = userdata.get('GEMINI_API_KEY')\n",
    "    if gemini_key:\n",
    "        get_ipython().system('pip install -q -r requirements-gemini.txt')\n",
    "        os.environ['GEMINI_API_KEY'] = gemini_key\n",
    "        os.environ['GEMINI_FALLBACK'] = '1'\n",
    "        os.environ.setdefault('GEMINI_MODEL_ID', 'gemini-2.5-flash')\n",
    "        del gemini_key\n",
    "        has_gemini_fallback = True\n",
    "        print('✅ Fallback Gemini API aktif (Colab Secret GEMINI_API_KEY ditemukan).')\n",
    "except Exception as e:\n",
    "    print('ℹ️ GEMINI_API_KEY belum diset di Colab Secrets (opsional untuk fallback tanpa GPU):', type(e).__name__)\n",
    "\n",
    "# 2) SET True hanya jika ingin mencoba Gemma 4 lokal di Colab GPU sebagai model utama.\n",
    "ENABLE_GEMMA = False\n",
    "if ENABLE_GEMMA:\n",
    "    import torch\n",
    "    if not torch.cuda.is_available():\n",
    "        if has_gemini_fallback:\n",
    "            print('GPU tidak aktif; saat checkbox AI dicentang di UI, app akan otomatis memakai fallback Gemini API.')\n",
    "        else:\n",
    "            raise RuntimeError('Pilih T4 GPU di Runtime > Change runtime type, atau set Colab Secret GEMINI_API_KEY untuk fallback.')\n",
    "    else:\n",
    "        # Pastikan bitsandbytes >= 0.46.1 dan accelerate terinstal untuk kuantisasi 4-bit\n",
    "        get_ipython().system('pip install -q -U \"bitsandbytes>=0.46.1\" \"accelerate>=1.1.0\" transformers')\n",
    "        subprocess.run([sys.executable, '-m', 'pip', 'install', '-U', '-r', 'requirements-gemma.txt'], check=True)\n",
    "        os.environ['GEMMA_4BIT'] = '1'\n",
    "        os.environ['GEMMA_MODEL_ID'] = 'google/gemma-4-E2B-it'\n",
    "        try:\n",
    "            from google.colab import userdata\n",
    "            hf_token = userdata.get('HF_TOKEN')\n",
    "            if hf_token:\n",
    "                from huggingface_hub import login\n",
    "                login(token=hf_token, add_to_git_credential=False)\n",
    "                del hf_token\n",
    "                print('Hugging Face authentication configured.')\n",
    "        except Exception as e:\n",
    "            print('Colab secret HF_TOKEN belum diset:', type(e).__name__)\n",
    "        print('Gemma siap digunakan ketika opsi checkbox diaktifkan di UI.')\n",
    "else:\n",
    "    if has_gemini_fallback:\n",
    "        print('Gemma lokal dilewati; checkbox AI di UI siap memakai fallback Gemini API tanpa GPU.')\n",
    "    else:\n",
    "        print('Skip Gemma & Gemini. Forensic engine inti berjalan penuh tanpa GPU.')"
]

with open('notebooks/VeriFile_HackDay_Colab.ipynb', 'w', encoding='utf-8') as f:
    json.dump(nb, f, indent=1, ensure_ascii=False)
print('Successfully saved clean notebooks/VeriFile_HackDay_Colab.ipynb')

