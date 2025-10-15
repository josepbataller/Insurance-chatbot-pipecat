import os
import asyncio
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import Response
from twilio.twiml.voice_response import VoiceResponse, Connect
from dotenv import load_dotenv
from loguru import logger

# Import your existing bot setup
from chatbot import run_bot
from pipecat.runner.types import RunnerArguments

load_dotenv(override=True)

app = FastAPI()


@app.post("/voice")
async def voice_webhook(request: Request):
    """
    This endpoint is called by Twilio when a call starts.
    It responds with TwiML that tells Twilio to open a WebSocket
    to /stream (below), which will carry audio in real-time.
    """
    logger.info("📞 Incoming call received from Twilio")

    response = VoiceResponse()
    connect = Connect()
    connect.stream(url="wss://your-ngrok-url.ngrok.io/stream")
    response.append(connect)

    return Response(content=str(response), media_type="application/xml")


@app.websocket("/stream")
async def websocket_stream(websocket: WebSocket):
    """
    This is where Twilio streams audio to and from the bot.
    The WebSocket connection handles bidirectional audio.
    """
    await websocket.accept()
    logger.info("🔊 Twilio WebSocket connected")

    # Create a dummy RunnerArguments for Pipecat
    runner_args = RunnerArguments(transport="webrtc", handle_sigint=False)

    # Run your existing Pipecat bot (non-blocking)
    bot_task = asyncio.create_task(run_bot(transport=None, runner_args=runner_args))

    try:
        while True:
            data = await websocket.receive_text()
            logger.debug(f"Received data from Twilio: {data}")
            # You can forward this data to your Pipecat bot here if needed
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        await websocket.close()
        logger.info("🔌 WebSocket closed")
        bot_task.cancel()
