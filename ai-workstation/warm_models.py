"""Download and smoke-test verified public model weights on the AI host only."""
import os, pathlib, json, traceback
root = pathlib.Path(os.environ.get("AUTOTRADER_AI_HOME",str(pathlib.Path(__file__).resolve().parent)))
os.environ["HF_HOME"] = str(root / "cache" / "huggingface")
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"
print("Starting model initialization...", flush=True)
try:
    import lightgbm
    print("LIGHTGBM_READY", lightgbm.__version__, flush=True)
    from transformers import pipeline
    news = pipeline("text-classification", model="ProsusAI/finbert", device=-1)
    result = news("Revenue rose while the company increased its cash-flow guidance.")
    print("FINBERT_READY", json.dumps(result), flush=True)
except Exception as e:
    print("FINBERT_OR_LIGHTGBM_ERROR", type(e).__name__, str(e)[:500], flush=True)
try:
    import torch
    from chronos import BaseChronosPipeline
    model = BaseChronosPipeline.from_pretrained("amazon/chronos-bolt-tiny", device_map="cpu", torch_dtype=torch.float32)
    context=torch.tensor([0.001,-0.003,0.002,0.006,-0.001,0.002,0.004,-0.002]*8,dtype=torch.float32)
    forecast=model.predict(context, prediction_length=1)
    print("CHRONOS_READY", str(forecast.shape),str(forecast.detach().cpu().numpy().tolist())[:400],flush=True)
except Exception as e:
    print("CHRONOS_ERROR", type(e).__name__, str(e)[:800], flush=True)