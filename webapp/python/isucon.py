import meinheld.patch
meinheld.patch.patch_socket()

import os
import json

import pymysql
from pymysql.cursors import DictCursor
from threading import local

import flask
import re
import time
import jinja2
from jinja2 import evalcontextfilter, Markup, escape, Environment


config = json.load(open('../config/hosts.json'))

ctx = local()

class ConnectionPool(local):
    @property
    def con(self):
        if not hasattr(self, '_con'):
            self._con = self._get_con()
        return self._con

    def _get_con(self):
        #host = str(config['servers']['database'][0])
        host = 'localhost'
        return pymysql.connect(
                    host=host,
                    user='isuconapp',
                    passwd='isunageruna',
                    db='isucon',
                    charset='utf8',
                    )

db = ConnectionPool()

print config

app = flask.Flask(__name__)

jinja_env = Environment(loader=jinja2.FileSystemLoader('views'))

def render(template, **params):
    return jinja_env.get_template(template).render(**params)


def fetch_recent_commented_articles():
    global _recent_articles
    cur = db.con.cursor(DictCursor)
    cur.execute(
            'SELECT a.id, a.title FROM comment c INNER JOIN article a ON c.article = a.id '
            'GROUP BY a.id ORDER BY MAX(c.created_at) DESC LIMIT 10')
    _recent_articles = cur.fetchall()

_recent_articles_cache = None
_recent_articles_cache_fetched = None

def get_recent_commented_articles():
    global _recent_articles_cache
    global _recent_articles_cache_fetched
    if _recent_articles_cache is None or _recent_articles_cache_fetched + 3 < time.time():
        _recent_articles_cache = fetch_articles()
        _recent_articles_cache_fetched = time.time()
    return _recent_articles_cache


def fetch_articles():
    cur = db.con.cursor(DictCursor)
    cur.execute('SELECT id,title,body,created_at FROM article ORDER BY id DESC LIMIT 10')
    return cur.fetchall()

def fetch_article(id):
    cur = db.con.cursor(DictCursor)
    cur.execute('SELECT id,title,body,created_at FROM article WHERE id=%s', (id,))
    return cur.fetchone()

@app.route('/')
def index():
    return render("index.jinja",
        articles=fetch_articles(),
        recent_commented_articles=get_recent_commented_articles(),
        )

@app.route('/article/<int:articleid>')
def article(articleid):
    return render('article.jinja',
        article=fetch_article(articleid),
        recent_commented_articles=get_recent_commented_articles(),
        )

@app.route('/post', methods=('GET', 'POST'))
def post():
    if flask.request.method == 'GET':
        return render("post.jinja", recent_commented_articles=get_recent_commented_articles())
    cur = db.con.cursor()
    cur.execute("INSERT INTO article SET title=%s, body=%s", (flask.request.form['title'], flask.request.form['body']))
    db.con.commit()
    return flask.redirect('/')

@app.route('/comment/<int:articleid>', methods=['POST'])
def comment(articleid):
    cur = db.con.cursor()
    form = flask.request.form
    cur.execute("INSERT INTO comment SET article=%s, name=%s, body=%s",
                (articleid, form['name'], form['body'])
                )
    db.con.commit()
    return flask.redirect('/')


_cache = {}

def prepare_static(scan_dir, prefix='/static/'):
    for dir, _, files in os.walk(scan_dir):
        for f in files:
            content_type = 'text/plain'
            if f.endswith('.css'):
                content_type = 'text/css'
            elif f.endswith('.js'):
                content_type = 'application/javascript'
            elif f.endswith(('.jpg', '.jpeg')):
                content_type = 'image/jpeg'
            p = os.path.join(dir, f)
            data = open(p).read()
            _cache[prefix + os.path.relpath(p, scan_dir)] = (
                    [('Content-Length', str(len(data))),
                     ('Content-Type', content_type),
                     ], data)
    #print _cache.keys()

def cache_middleware(app):
    def get_cache(env, start):
        path = env['PATH_INFO']
        if env['REQUEST_METHOD'] == 'GET' and path in _cache:
            head, body = _cache[path]
            start("200 OK", head)
            return [body]
        return app(env, start)
    return get_cache


prepare_static('../staticfiles', '/')
app.wsgi_app = cache_middleware(app.wsgi_app)

if __name__ == '__main__':
    #app.run(host='0.0.0.0', port=5000)
    import meinheld
    meinheld.set_access_logger(None)
    meinheld.set_backlog(128)
    meinheld.listen(('0.0.0.0', 5000))
    meinheld.run(app)
