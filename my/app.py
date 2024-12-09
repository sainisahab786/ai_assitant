import os
import base64
import json
import asyncio
import time
from datetime import datetime
from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import HTMLResponse
from fastapi.websockets import WebSocketDisconnect
from ibm_watson import SpeechToTextV1, TextToSpeechV1, AssistantV2
from ibm_cloud_sdk_core.authenticators import IAMAuthenticator
from twilio.twiml.voice_response import VoiceResponse, Connect

# Watson Credentials
STT_API_KEY = 'cGoDyVyzeMA6t9ScjTsqPHyWkE1PrVlA_WU4N-69g7FS'
TTS_API_KEY = 'Jd-deDjHrPDgJWHJj8LcBFXynoU8hBxpQAH_8BcQfb43'
ASSISTANT_API_KEY = '5JsxAzUT0wBFBHx6RiElA1-xls80dLPPGEzhJxD1BJTT'
ASSISTANT_ID = '78935058-e696-43c1-8782-18e7a48f3a6f'

# Initialize Watson Services
stt_authenticator = IAMAuthenticator(STT_API_KEY)
speech_to_text = SpeechToTextV1(authenticator=stt_authenticator)
speech_to_text.set_service_url(
    'https://api.au-syd.speech-to-text.watson.cloud.ibm.com/instances/ec3a80af-af43-4877-bd43-f2eeb0f3ecc5'
)

tts_authenticator = IAMAuthenticator(TTS_API_KEY)
text_to_speech = TextToSpeechV1(authenticator=tts_authenticator)
text_to_speech.set_service_url(
    'https://api.au-syd.text-to-speech.watson.cloud.ibm.com/instances/efc575b7-f547-4532-ac9b-96a0d5283b77'
)

assistant_authenticator = IAMAuthenticator(ASSISTANT_API_KEY)
assistant = AssistantV2(
    version='2024-08-25',
    authenticator=assistant_authenticator
)
assistant.set_service_url(
    'https://api.us-south.assistant.watson.cloud.ibm.com/instances/65f8e216-8bef-4e80-9aa1-0c3909617af0'
)

# FastAPI application
app = FastAPI()

@app.get("/", response_class=HTMLResponse)
async def index_page():
    return HTMLResponse("<h1>Twilio Media Stream with IBM Watson is running!</h1>")

@app.api_route("/incoming-call", methods=["GET", "POST"])
async def handle_incoming_call(request: Request):
    """Handle incoming call and return TwiML response to connect to Media Stream."""
    response = VoiceResponse()
    response.say("Connecting your call to the Watson AI assistant.")
    connect = Connect()
    connect.stream(url='wss://f9d6-49-43-6-6.ngrok-free.app/media-stream')
    response.append(connect)
    return HTMLResponse(content=str(response), media_type="application/xml")

@app.websocket("/media-stream")
async def handle_media_stream(websocket: WebSocket):
    """Handle WebSocket connections between Twilio and Watson with improved silence detection."""
    await websocket.accept()
    stream_sid = None
    audio_buffer = bytearray()
    last_audio_time = time.time()  # Track the last audio timestamp
    processed_transcripts = set()  # Keep track of processed transcripts to avoid duplicates

    print("WebSocket connection accepted.")
    try:
        while True:
            message = await websocket.receive_text()
            data = json.loads(message)

            if data.get("event") == "media":
                audio_chunk = base64.b64decode(data["media"]["payload"])
                audio_buffer.extend(audio_chunk)
                last_audio_time = time.time()  # Update the timestamp on receiving audio

                # Process audio buffer when it reaches a certain size for efficiency
                if len(audio_buffer) >= 800:
                    transcript = await transcribe_audio(audio_buffer)
                    if transcript and transcript not in processed_transcripts:
                        processed_transcripts.add(transcript)  # Mark as processed
                        assistant_response = await get_assistant_response(transcript)
                        tts_audio = synthesize_audio(assistant_response)
                        if tts_audio:
                            await send_audio_to_twilio(websocket, stream_sid, tts_audio)

                    audio_buffer.clear()

            elif data.get("event") == "start":
                stream_sid = data["start"]["streamSid"]
                print(f"Stream started: {stream_sid}")

                intro_audio = synthesize_audio("Now you can ask me something.")
                if intro_audio:
                    await send_audio_to_twilio(websocket, stream_sid, intro_audio)

            elif data.get("event") == "stop":
                print("Stream stopped.")
                break

            # Detect silence (no new audio chunks for 2.5 seconds)
            if time.time() - last_audio_time > 2.5 and len(audio_buffer) > 0:
                print("Silence detected. Processing audio buffer...")
                transcript = await transcribe_audio(audio_buffer)
                if transcript and transcript not in processed_transcripts:
                    processed_transcripts.add(transcript)  # Mark as processed
                    assistant_response = await get_assistant_response(transcript)
                    tts_audio = synthesize_audio(assistant_response)
                    if tts_audio:
                        await send_audio_to_twilio(websocket, stream_sid, tts_audio)

                audio_buffer.clear()  # Clear the buffer after processing

    except WebSocketDisconnect:
        print("WebSocket disconnected.")
    except Exception as e:
        print(f"Error: {e}")



async def send_audio_to_twilio(websocket, stream_sid, audio):
    """Send synthesized audio back to Twilio."""
    try:
        start_time = time.time()

        await websocket.send_json({
            "event": "media",
            "streamSid": stream_sid,
            "media": {
                "payload": base64.b64encode(audio).decode('utf-8')
            }
        })

        end_time = time.time()
        print(f"Time taken to send audio: {end_time - start_time:.2f} seconds")
    except Exception as e:
        print(f"Error sending audio: {e}")


async def transcribe_audio(audio_buffer):
    """Transcribe audio using Watson Speech-to-Text."""
    try:
        start_time = time.time()

        result = speech_to_text.recognize(
            audio=audio_buffer,
            content_type="audio/mulaw;rate=8000",
            model="en-US_NarrowbandModel"
        ).get_result()

        end_time = time.time()
        print(f"Time taken for transcription: {end_time - start_time:.2f} seconds")

        if result.get("results"):
            return result["results"][0]["alternatives"][0]["transcript"]
    except Exception as e:
        print(f"Error during transcription: {e}")
    return None

async def get_assistant_response(text):
    """Get response from Watson Assistant."""
    try:
        start_time = time.time()

        session = assistant.create_session(assistant_id=ASSISTANT_ID).get_result()
        session_id = session["session_id"]

        response = assistant.message(
            assistant_id=ASSISTANT_ID,
            session_id=session_id,
            input={"message_type": "text", "text": text}
        ).get_result()

        assistant.delete_session(assistant_id=ASSISTANT_ID, session_id=session_id)

        end_time = time.time()
        print(f"Time taken for Assistant response: {end_time - start_time:.2f} seconds")

        if response.get("output", {}).get("generic"):
            return response["output"]["generic"][0]["text"]
    except Exception as e:
        print(f"Error in Assistant response: {e}")
    return "I'm sorry, I couldn't process that."

def synthesize_audio(text):
    """Convert text to speech using Watson Text-to-Speech."""
    try:
        start_time = time.time()

        response = text_to_speech.synthesize(
            text,
            accept="audio/mulaw;rate=8000",
            voice="en-US_AllisonV3Voice"
        ).get_result()

        end_time = time.time()
        print(f"Time taken for Text-to-Speech: {end_time - start_time:.2f} seconds")

        return response.content
    except Exception as e:
        print(f"Error during text-to-speech: {e}")
    return None

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5050)