import json
import asyncio
from typing import Optional, Dict, Any

def get_api_key() -> str:
    import sys
    from pathlib import Path
    
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).parent
    else:
        base = Path(__file__).resolve().parent.parent
        
    config_path = base / "config" / "api_keys.json"
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)["gemini_api_key"]
    except Exception:
        return ""

def predict_market(parameters: dict = None, player=None, speak=None) -> str:
    """
    Acts as a Swarm Predictor. Gathers context, synthesizes an analysis, 
    and returns a structured prediction on the trajectory of a market.
    """
    params = parameters or {}
    asset = params.get("asset", "EURUSD")
    context = params.get("context", "")

    if speak:
        speak(f"Initiating swarm prediction sequence for {asset}.")

    try:
        import google.generativeai as genai
        genai.configure(api_key=get_api_key())
        
        # Use a high-intelligence model for the master prediction
        model = genai.GenerativeModel("gemini-2.5-pro")
        
        prompt = f"""
        You are the Master Prediction Node of Axiom. 
        You are tasked with analyzing the market trajectory for the asset: {asset}.
        
        Additional context provided by the user or recent queries:
        {context}
        
        Perform a Swarm-Intelligence style prediction:
        1. Macro Analysis (Fundamental forces at play)
        2. Micro Analysis (Structural trends, momentum)
        3. Sentiment (What is the current prevailing bias?)
        4. Verdict (Bullish, Bearish, or Neutral) with a specific confidence percentage.
        
        Keep your response highly analytical, professional, and brutal in its logic.
        """
        
        response = model.generate_content(prompt)
        text = response.text.strip()
        
        if speak:
            speak(f"Market prediction for {asset} is complete. You can view the full diagnostic in the logs.")
        
        return f"Prediction Diagnostic for {asset}:\n\n{text}"

    except Exception as e:
        error_msg = f"Prediction engine failed: {str(e)}"
        if speak:
            speak("My prediction engines encountered an anomaly.")
        return error_msg
