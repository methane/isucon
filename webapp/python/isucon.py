import greenlet
mein_greenlet = greenlet.getcurrent()

import os
import json
import gzip
from cStringIO import StringIO

import pymysql
from pymysql.cursors import DictCursor
from threading import local

import flask
import re
import time
import jinja2
from jinja2 import evalcontextfilter, Markup, escape, Environment


config = json.load(open('../config/hosts.json'))
print config


def compress(b):
    s = StringIO()
    f = gzip.GzipFile(None, 'wb', 9, fileobj=s)
    f.write(b)
    f.flush()
    return s.getvalue()

class DB(object):
    @property
    def con(self):
        host = str(config['servers']['database'][0])
        return pymysql.connect(
                    host=host,
                    user='isuconapp',
                    passwd='isunageruna',
                    db='isucon',
                    charset='utf8',
                    )

db = DB()

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
    con = db.con
    cur = con.cursor()
    cur.execute("INSERT INTO article SET title=%s, body=%s", (flask.request.form['title'], flask.request.form['body']))
    print cur.lastrowid
    con.commit()
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
                     ], data) * 2
    #print _cache.keys()

def cache_middleware(app):
    def get_cache(env, start):
        path = env['PATH_INFO']
        if env['REQUEST_METHOD'] == 'GET' and path in _cache:
            if 'gzip' in env.get('HTTP_ACCEPT_ENCODING', ''):
                head, body = _cache[path][2:]
            else:
                head, body = _cache[path][:2]
            start("200 OK", head)
            return [body]
        return app(env, start)
    return get_cache


def update_all_cache():
    text_html = ('Content-Type', 'text/html')
    gzip_enc = ('Content-Encoding', 'gzip')
    def cl(d):
        return ('Content-Length', str(len(d)))

    data = index().encode('utf-8')
    cdata = compress(data)
    _cache['/'] = ([text_html, cl(data)], data,
            [text_html, gzip_enc, cl(cdata)], cdata)

    data = render("post.jinja",
            recent_commented_articles=get_recent_commented_articles()).encode('utf-8')
    cdata = compress(data)
    _cache['/post'] = ([text_html, cl(data)], data,
            [text_html, gzip_enc, cl(cdata)], cdata)

    articleid = 0
    while True:
        print articleid
        cur = db.con.cursor(DictCursor)
        cur.execute('SELECT id,title,body,created_at FROM article WHERE id>%s LIMIT 100', (articleid,))
        for row in cur:
            articleid = row['id']
            data = render('article.jinja',
                    article=row,
                    recent_commented_articles=get_recent_commented_articles(),
                    ).encode('utf-8')
            cdata = compress(data)
            _cache['/article/'+str(articleid)] = (
                    [text_html, cl(data)], data,
                    [text_html, gzip_enc, cl(cdata)], cdata
                    )
        if cur.rowcount == 0:
            break

def sleep(secs):
    t = time.time() + secs
    while 1:
        meinheld.schedule_call(1, greenlet.getcurrent().switch)
        mein_greenlet.switch()
        if time.time() > t:
            break

def background_update():
    update_all_cache()
    print "bg"
    #meinheld.schedule_call(5, background_update)

prepare_static('../staticfiles', '/')
app.wsgi_app = cache_middleware(app.wsgi_app)

if __name__ == '__main__':
    #app.run(host='0.0.0.0', port=5000)
    import meinheld
    meinheld.set_access_logger(None)
    meinheld.set_backlog(128)
    meinheld.set_keepalive(0)
    meinheld.listen(('0.0.0.0', 5000))

    background_update()
    meinheld.run(app)
