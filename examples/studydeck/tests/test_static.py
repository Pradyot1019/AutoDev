def test_root_serves_html(client):
    response = client.get('/')
    assert response.status_code == 200
    assert 'text/html' in response.headers['content-type']
    assert '<html' in response.text.lower()


def test_static_css_served(client):
    response = client.get('/static/style.css')
    assert response.status_code == 200
    assert 'text/css' in response.headers['content-type']
