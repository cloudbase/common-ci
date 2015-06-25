import oauth.oauth as oauth
import httplib2
import uuid
import urlparse
import json
import datetime


DEFAULT = 0
#: The node has been created and has a system ID assigned to i
NEW = 0
#: Testing and other commissioning steps are taking place.
COMMISSIONING = 1
#: The commissioning step failed.
FAILED_COMMISSIONING = 2
#: The node can't be contacted.
MISSING = 3
#: The node is in the general pool ready to be deployed.
READY = 4
#: The node is ready for named deployment.
RESERVED = 5
#: The node has booted into the operating system of its owner'
#: and is ready for use.
DEPLOYED = 6
#: The node has been removed from service manually until an ad
#: overrides the retirement.
RETIRED = 7
#: The node is broken: a step in the node lifecyle failed.
#: More details can be found in the node's event log.
BROKEN = 8
#: The node is being installed.
DEPLOYING = 9
#: The node has been allocated to a user and is ready for depl
ALLOCATED = 10
#: The deployment of the node failed.
FAILED_DEPLOYMENT = 11
#: The node is powering down after a release request.
RELEASING = 12
#: The releasing of the node failed.
FAILED_RELEASING = 13
#: The node is erasing its disks.
DISK_ERASING = 14
#: The node failed to erase its disks.
FAILED_DISK_ERASING = 15



class MaaSBaseClass(object):

    VERBS = (
        "GET",
        "PUT",
        "POST",
        "DELETE",
    )

    def __init__(self, maas_url, token):
        self.maas_url = maas_url
        self.url = urlparse.urlparse(self.maas_url)
        self.token = token
        self._parse_token(token)

    def _parse_token(self, token):
        t = token.split(":")
        if len(t) != 3:
            raise ValueError("Invalid MaaS token")
        self.consumer_key = t[0]
        self.key = t[1]
        self.secret = t[2]

    def _validate_verb(self, verb, body):
        if verb not in self.VERBS:
            raise ValueError("%s is not supported" % verb)
        if verb == "DELETE":
            # DELETE requests must have body None
            return None
        return body

    def _check_response(self, response):
        status = response.get("status")
        if int(status) > 299:
            raise Exception("Request returned status %s" % status)

    @property
    def _api_path(self):
        uri = "api/1.0/"
        return "%s/%s" % (self.url.path, uri)

    def _get_resource_uri(self, op=None):
        resource = self.RESOURCE
        if self.RESOURCE.startswith(self._api_path):
            resource = self.RESOURCE[len(self._api_path):]

        uri = "/api/1.0/%s/" % resource.strip("/")
        if op:
            uri = "%s?op=%s" % (uri, op)
        return uri 

    def _dispatch(self, uri, method, body=None):
        body = self._validate_verb(method, body)

        resource_tok_string = "oauth_token_secret=%s&oauth_token=%s" % (self.secret, self.key)
        resource_token = oauth.OAuthToken.from_string(resource_tok_string)
        consumer_token = oauth.OAuthConsumer(self.consumer_key, "")

        oauth_request = oauth.OAuthRequest.from_consumer_and_token(
            consumer_token, token=resource_token, http_url=self.maas_url,
            parameters={'oauth_nonce': uuid.uuid4().get_hex()})

        oauth_request.sign_request(
            oauth.OAuthSignatureMethod_PLAINTEXT(), consumer_token,
            resource_token)

        headers = oauth_request.to_header()
        url = "%s%s" % (self.maas_url, uri)
        http = httplib2.Http()
        response, content = http.request(url, method, body=body, headers=headers)
        self._check_response(response)
        body = json.loads(content)
        return body


class ResourceMixin(object):

    def _refresh_data(self):
        if self._requested is None:
            self._data = self._get()
            self._requested = datetime.datetime.utcnow()

        delta = datetime.datetime.utcnow() - self._requested
        if delta > datetime.timedelta(seconds=30):
            self._data = self._get()
            self._requested = datetime.datetime.utcnow()

        if self._data is None:
            self._data = self._get()
            self._requested = datetime.datetime.utcnow()
            return

    @property
    def data(self):
        self._refresh_data()
        return self._data


class Node(MaaSBaseClass, ResourceMixin):

    def __init__(self, maas_url, maas_token, resource):
        super(Node, self).__init__(maas_url, maas_token)
        self.RESOURCE = resource
        self._data = None
        self._requested = None

    def status(self):
        self._refresh_data()
        status = self.data.get("status")
        if status:
            return int(status)

    def substatus(self):
        self._refresh_data()                                                    
        status = self.data.get("substatus")                                        
        if status:                                                              
            return int(status)

    def _get(self):
        nodes = self._get_resource_uri()
        return self._dispatch(nodes, "GET")


class Nodes(MaaSBaseClass):

    RESOURCE = "nodes"

    def list(self):
        nodes = self._get_resource_uri(op="list")
        return self._dispatch(nodes, "GET")

    def get(self, resource):
        return Node(self.maas_url, self.token, resource)
