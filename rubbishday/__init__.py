import logging
import os
import requests
import json
import re
import azure.functions as func
import ask_sdk_core.utils as ask_utils

from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from ask_sdk_webservice_support.webservice_handler import WebserviceSkillHandler
from ask_sdk_core.dispatch_components import AbstractRequestHandler, AbstractExceptionHandler

from ask_sdk_core.skill_builder import CustomSkillBuilder
from ask_sdk_core.api_client import DefaultApiClient
from ask_sdk_core.utils import is_request_type, is_intent_name
from ask_sdk_model.ui import AskForPermissionsConsentCard
from ask_sdk_model.ui import StandardCard
from ask_sdk_model.services import ServiceException

permissions = ["read::alexa:device:all:address"]
# Location Consent permission to be shown on the card. More information
# can be checked at the following URL:
# https://developer.amazon.com/docs/custom-skills/device-address-api.html#sample-response-with-permission-card

def main(req: func.HttpRequest) -> func.HttpResponse:

    logging.info('Python HTTP trigger function processing a request.')
         
    skill_builder = CustomSkillBuilder(api_client=DefaultApiClient())
    skill_builder.skill_id = os.environ["RUBBISHDAY_SKILL_ID"]
    skill_builder.add_request_handler(LaunchRequestHandler())
    skill_builder.add_request_handler(HelpIntentHandler())
    skill_builder.add_request_handler(CancelOrStopIntentHandler())
    skill_builder.add_request_handler(SessionEndedRequestHandler())
    skill_builder.add_request_handler(ReadCollectionCalender())
    skill_builder.add_exception_handler(CatchAllExceptionHandler())

    webservice_handler = WebserviceSkillHandler(skill=skill_builder.create())
    response = webservice_handler.verify_request_and_dispatch(req.headers, req.get_body().decode("utf-8"))
    return func.HttpResponse(json.dumps(response),mimetype="application/json")

class LaunchRequestHandler(AbstractRequestHandler):
    """Handler for LaunchRequest."""
    def can_handle(self, handler_input):
        return ask_utils.is_request_type("LaunchRequest")(handler_input)

    def handle(self, handler_input):

        logging.info("Called Skill Handler for LaunchRequest Intent.")

        speak_output = "Hello!  I can help you with what types of rubbish you need to put out.  Just say <break time='0.5s'/>'what's being collected this week'."
        return (
            handler_input.response_builder
                .speak(speak_output)
                .ask(speak_output)
                .response
        )

class SessionEndedRequestHandler(AbstractRequestHandler):
    """Handler for Session End Request."""
    def can_handle(self, handler_input):
        return ask_utils.is_request_type("SessionEndedRequest")(handler_input)

    def handle(self, handler_input):

        logging.info("Called Skill Handler for SessionEndedRequest Intent.")

        speak_output = "Thanks for using rubbish day! Bye!"

        return (
            handler_input.response_builder
                .speak(speak_output)
                .ask(speak_output)
                .response
        )

class HelpIntentHandler(AbstractRequestHandler):
    """Handler for Help Intent."""
    def can_handle(self, handler_input):
        return ask_utils.is_intent_name("AMAZON.HelpIntent")(handler_input)

    def handle(self, handler_input):

        logging.info("Called Skill Handler for AMAZON.HelpIntent Intent.")

        speak_output = "Hello!  I can help you with what types of rubbish you need to put out.  Just say <break time='0.5s'/>'what's being collected this week'."

        return (
            handler_input.response_builder
                .speak(speak_output)
                .ask(speak_output)
                .response
        )

class CancelOrStopIntentHandler(AbstractRequestHandler):
    """Single handler for Cancel and Stop Intent."""
    def can_handle(self, handler_input):
        return (ask_utils.is_intent_name("AMAZON.CancelIntent")(handler_input) or
                ask_utils.is_intent_name("AMAZON.StopIntent")(handler_input))

    def handle(self, handler_input):
        speak_output = "Goodbye from the rubbish day skill!"

        logging.info("Called Skill Handler for Cancel or Stop Intents.")

        return (
            handler_input.response_builder
                .speak(speak_output)
                .response
        )

class CatchAllExceptionHandler(AbstractExceptionHandler):
    """Generic error handling to capture any syntax or routing errors. If you receive an error
    stating the request handler chain is not found, you have not implemented a handler for
    the intent being invoked or included it in the skill builder below.
    """
    def can_handle(self, handler_input, exception):
        return True

    def handle(self, handler_input, exception):
        logging.error(exception, exc_info=True)
        speak_output = "Sorry, I had trouble doing what you asked. Please try again."

        return(
            handler_input.response_builder
                .speak(speak_output)
                .ask(speak_output)
                .response
        )

class ReadCollectionCalender(AbstractRequestHandler):
            
    def can_handle(self, handler_input):
        return is_intent_name("ReadCollectionCalender")(handler_input)

    def handle(self, handler_input):

        # Check if we're in a test version of the function and can log request information.  We won't do this in production
        # is it would mean we would be logging customers requests including address info which isn't good for privacy!           
        try:
            if os.environ["ISTESTENV"] == 'true':
                requestlogging = True
                logging.info('Function running under test so enabling logging of requests.')
            else:
                requestlogging = False
        except KeyError as error:
            requestlogging = False

        req_envelope = handler_input.request_envelope
        response_builder = handler_input.response_builder
        service_client_fact = handler_input.service_client_factory        

        device_id = req_envelope.context.system.device.device_id
        
        if requestlogging:
            logging.info('Received request from deviceid: ' + device_id)

        # Check that we have permission to get the address of the Alexa device that called this skill
        # If not, we tell the user we don't have permissing and exit the function
        if not (req_envelope.context.system.user.permissions and
                req_envelope.context.system.user.permissions.consent_token):
            response_builder.speak('Please enable Location permissions in the Amazon Alexa app.')
            response_builder.set_card(
                AskForPermissionsConsentCard(permissions=permissions))
            return response_builder.response

        # Use the SDK to call the Alexa API to get the Alexa device's address
        try:
            device_addr_client = service_client_fact.get_device_address_service()
            addr = device_addr_client.get_full_address(device_id)
        except ServiceException:
            logging.error('Error while attempting to get the Alexa devices address.')
            response_builder.speak('Sorry, there was an error attempting to get the location of your Alexa device.')
            return response_builder.response
        except Exception as e:
            logging.error('Unhandled exception while attempting to get the Alexa devices address.')
            raise e

        # If not address information is returned, exit the function returning a message to the user to ensure it is set.
        if addr.country_code is None and addr.postal_code is None:
            response_builder.speak("Could not get an address for this Alexa device.  Please set an address for this Alexa device in the Alexa app.")
            return response_builder.response

        # If the country_code is not GB, exit the function returning a message to the user.
        if addr.country_code != 'GB':
            logging.warn('Unsupported location.  Country code: ' + addr.country_code)
            response_builder.speak("Sorry, this skill does not currently support your country.")
            return response_builder.response
        elif requestlogging:
            logging.info('Supported country code: ' + addr.country_code)


        # Only Colchester Borough Council is currently supported.  If the device is not in a CO
        # postcode, exit the function returning a message to the user.
        result = re.search('\d', addr.postal_code)
        numericPosition = result.span()[0]
        postal_code_area = addr.postal_code[:numericPosition]
        if postal_code_area != 'CO':
            # NOTE: This is the only part of the function where we will log the users postcode.  This is only the start characters (the "postal code area")
            # and is to allow us to understand want locations users are trying to use the skill for and which may be worth adding
            logging.warn('Unsupported location.  Postal code area: ' + postal_code_area)
            response_builder.speak("Sorry, this skill does not currently support your location.")
            return response_builder.response
        elif requestlogging:
            logging.info('Supported postal code area: ' + postal_code_area)

        # Use Colchester Borough Council's API to get the collection info for the devices address
        if postal_code_area == 'CO':

            if requestlogging:
                logging.info('Using the Colchester Borough Council API (full postcode is ' + addr.postal_code + ').')
            
            postal_code = addr.postal_code.replace(' ', '%20')
            postal_code = postal_code.lower()
            api_url = 'https://www.colchester.gov.uk/_odata/LLPG?$filter=(new_postcoide eq \'' + postal_code + '\')'
               

            if requestlogging:
                logging.info('Calling CBC API: ' + api_url)

            try:
                response = requests.get(api_url)
            except Exception as error:
                logging.error('CBC API: Problem calling the address lookup API.  Error:  ' + str(error))
                response_builder.speak('Sorry, there was an error looking up your location in the database.')
                return response_builder.response

            if response.status_code != 200:
                logging.error('CBC API: Error ' + str(response.status_code) + ' - ' + response.reason + '. API call was: ' + api_url)
                response_builder.speak('Sorry, there was an error looking up your location in the database.')
                return response_builder.response

            data = response.json()

            if response.status_code == 200 and len(data["value"]) == 0:
                logging.warn('CBC API: Lookup for postcode' + addr.postal_code + ' returned 0 results. API call was: ' + api_url)
                response_builder.speak('Sorry, your location was not found in the database.')
                return response_builder.response

            llpgid = data["value"][0]["new_llpgid"]
            street = data["value"][0]["new_street"]

            # CBC recycling calendar lookup URL
            api_url = 'https://new-llpg-app.azurewebsites.net/api/calendar/' + llpgid

            if requestlogging:
                logging.info('Calling CBC API: ' + api_url)

            try:
                response = requests.get(api_url)
            except Exception as error:
                logging.error('CBC API: Problem calling the collection calender API.  Error:  ' + str(error))
                response_builder.speak('Sorry, there was an error looking up your collection calendar in the database.')
                return response_builder.response

            if response.status_code != 200:
                logging.error('CBC API Error: ' + str(response.status_code) + ' ' + response.reason + '. API call was: ' + api_url)
                response_builder.speak('Sorry, there was an error looking up your collection calendar in the database.')
                return response_builder.response

            data = response.json()

            # Find out what day of the week and the next date the collection is on
            try:
                for key, value in data['DatesOfFirstCollectionDays'].items():
                    collectionDay = key
                    nextCollectionDateStr = value
            except KeyError as error:
                logging.error('CBC API Error: Did not get usable \'DatesOffFirstCollectionDays\' data in the API respsonse. API call was: ' + api_url)
                response_builder.speak('Sorry, there was an error looking up your collection calendar in the database.')
                return response_builder.response
            except Exception as error:
                logging.error('CBC API Error: ' + str(response.status_code) + ' ' + response.reason + '. API call was: ' + api_url)
                response_builder.speak('Sorry, there was an error looking up your collection calendar in the database.')
                return response_builder.response

            # CBC's API always returns data for the next two weeks of collections.  Sometimes the collection data doesn't move forward until a few days after
            # the collection has been made.  If the 'nextCollectionDate' is in the past then we need to use the collection data for the second week, as the data
            # in the first week is now in the past.
            nextCollectionDateStr = nextCollectionDateStr.replace('T00:00:00','')
            nextCollectionDate = datetime.strptime(nextCollectionDateStr, '%Y-%m-%d')
            currentDate = datetime.now()

            if nextCollectionDate < currentDate:
                this_week = data['Weeks'][1]
            else:
                this_week = data['Weeks'][0]
                
            # Get all the waste types that are picked up this week and concatenate them into a single string and the correct punctuation
            # etc so that it makes sense when Alexa speaks it
            waste_types_text = ''
            counter = 1
            waste_type_count = len(this_week["Rows"][collectionDay])

            for waste_type in this_week["Rows"][collectionDay]:
                waste_types_text = waste_types_text + waste_type["Name"]
                # Punctuation to separate each waste type
                if counter == (waste_type_count - 1):
                    waste_types_text = waste_types_text + ' and '
                elif counter < waste_type_count:
                    waste_types_text = waste_types_text + ', '    
                counter += 1

            waste_types_text = waste_types_text.replace('/',' and ')
            print(waste_types_text)

            # Build the output strings
            speak_output = 'The rubbish collection day for ' + street + ' is ' + collectionDay + '.  The next collection is for ' + waste_types_text + '.'
            text_output = 'Collection day: ' + collectionDay + '.\n\n  Your next collection: ' + waste_types_text + '.'

            response_builder.set_card(
                StandardCard(
                    title="Rubbish Day",
                    text=text_output
                    #,
                    #image=ui.Image(
                    #    small_image_url="<Small Image URL>",
                    #    large_image_url="<Large Image URL>"
                    #)
                )
            )
            logging.info('Successfully looked up and returned collection schedule.')

            response_builder.speak(speak_output)
            return response_builder.response
