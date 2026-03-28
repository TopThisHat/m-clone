I need to refactor the agent to not use pydantic-ai but used a2a.  
I need the service to have an aws flag when true that it pulls two secrets.
One secret will have a PEM file used by azure identiy for credential
Another will have a config json which will have keys like endpoint, client_id, token_id.  I also when ENV is dev, uat or PROD ,the getting a token from azure must go via corporate proxy set via env CLOUDPROXY and port 11111 and use a cert which will be in cert/uat.cert
 
The call to openai will proxied via an endpoint from the config and a bearer token goten from the token_provider must be passed, along with an API key from the config.  