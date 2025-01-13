import os
import logging
from rhythms.services.linear_service import LinearService

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

def test_linear_api():
    try:
        # Initialize service
        service = LinearService()
        
        # Log token info (first few chars only for security)
        token = service.linear_token
        if token:
            logger.info(f"Token found: {token[:10]}...")
        else:
            logger.error("No token found!")
            return
            
        # Test simple viewer query first
        test_query = """
        query {
          viewer {
            id
            name
            email
          }
        }
        """
        
        logger.info("Testing simple viewer query...")
        result = service._execute_query(test_query)
        logger.info(f"Viewer query result: {result}")
        
        # If viewer query succeeds, test activity query
        logger.info("Testing activity query...")
        activity = service.get_user_activity(days=1)
        logger.info(f"Activity query result: {activity}")
        
    except Exception as e:
        logger.error(f"Error testing Linear API: {str(e)}")
        logger.error(f"Full error details: {vars(e)}")
        raise

if __name__ == "__main__":
    print("\n=== Testing Linear API Integration ===\n")
    test_linear_api() 