from fastapi import FastAPI, WebSocket, Request, WebSocketDisconnect, Response
from fastapi.middleware.cors import CORSMiddleware
from ibm_watson import SpeechToTextV1, TextToSpeechV1, AssistantV2
from ibm_cloud_sdk_core.authenticators import IAMAuthenticator
import base64
import json
from twilio.twiml.voice_response import VoiceResponse
import logging
import uvicorn

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

STT_API_KEY = 'cGoDyVyzeMA6t9ScjTsqPHyWkE1PrVlA_WU4N-69g7FS'
TTS_API_KEY = 'Jd-deDjHrPDgJWHJj8LcBFXynoU8hBxpQAH_8BcQfb43'
ASSISTANT_API_KEY = '5JsxAzUT0wBFBHx6RiElA1-xls80dLPPGEzhJxD1BJTT'
ASSISTANT_ID = '78935058-e696-43c1-8782-18e7a48f3a6f'

logger.info("Initializing IBM Watson Services...")
try:
    stt_authenticator = IAMAuthenticator(STT_API_KEY)
    speech_to_text = SpeechToTextV1(authenticator=stt_authenticator)
    speech_to_text.set_service_url(
        'https://api.au-syd.speech-to-text.watson.cloud.ibm.com/instances/ec3a80af-af43-4877-bd43-f2eeb0f3ecc5'
    )
    logger.info("Speech-to-Text service initialized.")

    tts_authenticator = IAMAuthenticator(TTS_API_KEY)
    text_to_speech = TextToSpeechV1(authenticator=tts_authenticator)
    text_to_speech.set_service_url(
        'https://api.au-syd.text-to-speech.watson.cloud.ibm.com/instances/efc575b7-f547-4532-ac9b-96a0d5283b77'
    )
    logger.info("Text-to-Speech service initialized.")

    assistant_authenticator = IAMAuthenticator(ASSISTANT_API_KEY)
    assistant = AssistantV2(
        version='2024-08-25',
        authenticator=assistant_authenticator
    )
    assistant.set_service_url(
        'https://api.us-south.assistant.watson.cloud.ibm.com/instances/65f8e216-8bef-4e80-9aa1-0c3909617af0'
    )
    logger.info("Assistant service initialized.")
except Exception as e:
    logger.error(f"Error initializing Watson services: {e}")
    raise

app = FastAPI()


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_credentials=True,
    allow_methods=["*"],  
    allow_headers=["*"],  
)

@app.get("/")
async def root():
    """
    Health check endpoint
    """
    logger.info("Health check endpoint hit.")
    return {"status": "active", "message": "Twilio-Watson integration service is running"}

@app.post("/media-stream")
async def media_stream(request: Request):
    """
    Handles the initial webhook from Twilio for media stream setup.
    """
    logger.info("Received POST request from Twilio.")
    
    try:
        # Define the response text
        response_text = "Hello! I'm your AI assistant. How can I help you today?"

        # Create a VoiceResponse object
        voice_response = VoiceResponse()

        # Add the text-to-speech response using Twilio's 'say' function
        voice_response.say(response_text, voice="alice")
        logger.info(f"Added text-to-speech response: {response_text}")

        # Start the media stream after the greeting
        start = voice_response.start()
        stream = start.stream(
            url="wss://7db4-49-43-6-185.ngrok-free.app/media-stream/ws",
            track="inbound_track"
        )
        stream.parameter(name="format", value="audio/x-mulaw;rate=8000")
        stream.parameter(name="channels", value="1")
        logger.info("Streaming instructions added to TwiML response.")

        # Add a pause to keep the connection alive
        voice_response.pause(length=60)
        
        return Response(
            content=str(voice_response),
            media_type="application/xml"
        )
    except Exception as e:
        logger.error(f"Error generating TwiML response: {e}")
        raise

audio_buffer = bytearray()

@app.websocket("/media-stream/ws")
async def websocket_endpoint(websocket: WebSocket):
    logger.info("WebSocket connection attempt received.")
    await websocket.accept()
    logger.info("WebSocket connection accepted.")

    is_connected = True
    skip_initial_chunks = True
    audio_buffer = bytearray()

    try:
        while is_connected:
            message = await websocket.receive_text()
            try:
                data = json.loads(message)
                event_type = data.get('event', 'unknown')

                if event_type == 'media':
                    audio_chunk = base64.b64decode(data["media"]["payload"])

                    if skip_initial_chunks:
                        skip_initial_chunks = False
                        continue

                    audio_buffer.extend(audio_chunk)

                    if len(audio_buffer) >= 3200:  # Process in chunks
                        transcription_result = speech_to_text.recognize(
                            audio=audio_buffer,
                            content_type='audio/mulaw;rate=8000',
                            model='en-US_NarrowbandModel',
                        ).get_result()

                        if transcription_result.get('results'):
                            transcript = transcription_result['results'][0]['alternatives'][0]['transcript']
                            logger.info(f"Transcribed text: {transcript}")

                            # Get Watson Assistant response
                            assistant_response = await get_assistant_response(transcript)
                            logger.info(f"Assistant response: {assistant_response}")

                            # Convert Assistant response to speech
                            tts_response = text_to_speech.synthesize(
                                text=assistant_response,
                                voice="en-US_AllisonV3Voice",
                                accept='audio/mulaw;rate=8000'
                            ).get_result()

                            audio_data = tts_response.content

                            audio_file_name = f"response_audio_{data.get('streamSid', 'unknown')}.ulaw"
                            with open(audio_file_name, "wb") as audio_file:
                                audio_file.write(audio_data)
                            logger.info(f"Saved synthesized audio to {audio_file_name}")

                            # Send audio back to Twilio
                            if len(audio_data) > 0:
                                media_response = {
                                    "event": "media",
                                    "streamSid": data.get("streamSid"),
                                    "media": {
                                        "payload": base64.b64encode(audio_data).decode('utf-8')
                                    }
                                }
                                await websocket.send_text(json.dumps(media_response))
                                logger.info("Synthesized audio sent back to Twilio.")
                            else:
                                logger.error("TTS returned an empty audio response. Skipping transmission.")
                        else:
                            logger.warning("No transcription detected. Skipping response.")
                        audio_buffer.clear()

            except json.JSONDecodeError:
                logger.error("Failed to parse message as JSON.")
                continue
            except Exception as e:
                logger.error(f"Error processing WebSocket message: {e}")
                continue
    except WebSocketDisconnect:
        is_connected = False
        logger.info("WebSocket disconnected.")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        is_connected = False
    finally:
        logger.info("Cleanup complete.")


async def get_assistant_response(text: str) -> str:

    ### response from Watson Assistant.
    logger.info(f"Sending message to Watson Assistant: {text}")
    try:
        # session
        session = assistant.create_session(
            assistant_id=ASSISTANT_ID
        ).get_result()
        session_id = session['session_id']
        logger.info(f"Assistant session created with ID: {session_id}")

        # Send message to assistant
        response = assistant.message(
            assistant_id=ASSISTANT_ID,
            session_id=session_id,
            input={'message_type': 'text', 'text': text}
        ).get_result()
        logger.info(f"Assistant response: {json.dumps(response, indent=2)}")

        # Clean up session
        assistant.delete_session(
            assistant_id=ASSISTANT_ID,
            session_id=session_id
        )
        logger.info(f"Assistant session {session_id} deleted.")

        # Extract and return response
        if response.get('output', {}).get('generic'):
            return response['output']['generic'][0]['text']
        else:
            return "I'm sorry, I couldn't understand that. Could you please rephrase?"
    except Exception as e:
        logger.error(f"Error in Watson Assistant response: {e}")
        return "I apologize, but I'm having trouble processing your request right now."

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )