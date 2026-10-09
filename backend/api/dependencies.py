"""Application-owned dependencies; no construction during request handling."""
def services(request):
    return request.app.state.services
