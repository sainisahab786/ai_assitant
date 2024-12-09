from ibm_watson import AssistantV2
from ibm_cloud_sdk_core.authenticators import IAMAuthenticator
from ibm_cloud_sdk_core.api_exception import ApiException

# Replace with your actual API key and Assistant ID
ASSISTANT_API_KEY = '5JsxAzUT0wBFBHx6RiElA1-xls80dLPPGEzhJxD1BJTT'
ASSISTANT_ID = '64827032-8273-4d6e-acd7-d87eb9427095'

# Set up the authenticator
assistant_authenticator = IAMAuthenticator(ASSISTANT_API_KEY)

# Initialize the Assistant service
assistant = AssistantV2(
    version='2021-06-14',  # Specify the correct API version
    authenticator=assistant_authenticator
)

# Set the Assistant service URL (check if this matches your region)
assistant.set_service_url('https://api.us-south.assistant.watson.cloud.ibm.com/instances/65f8e216-8bef-4e80-9aa1-0c3909617af0')

# Function to create a session
def create_assistant_session():
    try:
        print("Attempting to create a session with Watson Assistant...")
        
        # Log the assistant ID being used
        print(f"Using Assistant ID: {ASSISTANT_ID}")
        
        # Attempt to create a session
        session_id_response = assistant.create_session(assistant_id=ASSISTANT_ID)
        
        # Log the raw response for more insights
        print("Raw session creation response:")
        print(session_id_response)
        
        # Extract the session ID
        session_id = session_id_response.get_result().get('session_id')
        
        # Log confirmation of session ID retrieval
        if session_id:
            print(f"Session created successfully. Session ID: {session_id}")
        else:
            print("Warning: Session ID not found in the response.")
        
        return session_id
    
    except ApiException as e:
        # Log detailed error information
        print("APIException encountered during session creation:")
        print(f"Status Code: {e.code}")
        print(f"Error Message: {e.message}")
        print(f"Global Transaction ID: {e.global_transaction_id}")
        
        # Print full error response if available
        if hasattr(e, 'http_response'):
            print("Full HTTP response:")
            print(e.http_response)
        
        return None
    
    except Exception as ex:
        # Log any other unexpected errors with a stack trace
        print("Unexpected error encountered during session creation:")
        print(ex)
        import traceback
        traceback.print_exc()
        
        return None


# Test the session creation
if __name__ == "__main__":
    create_assistant_session()
