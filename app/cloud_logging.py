"""
Google Cloud Logging integration
Sends logs to both stdout (for systemd) and Google Cloud Logging (for GCP Console)
"""
import logging
import os

def setup_cloud_logging():
    """Set up Google Cloud Logging if running on GCP"""
    try:
        # Only set up Cloud Logging if we're on GCP
        if os.path.exists('/opt/career-ops-backend'):
            from google.cloud import logging as cloud_logging
            
            # Create Cloud Logging client
            client = cloud_logging.Client()
            
            # Set up Cloud Logging handler
            handler = client.get_default_handler()
            
            # Get root logger and add cloud handler
            root_logger = logging.getLogger()
            root_logger.addHandler(handler)
            
            logging.info("✅ Google Cloud Logging enabled - logs will appear in GCP Console")
            return True
    except Exception as e:
        logging.warning(f"Could not enable Google Cloud Logging: {e}")
        logging.info("Logs will only appear in systemd journal")
        return False
    
    return False
