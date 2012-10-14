# coding: utf-8
import greenlet
mein_greenlet = greenlet.getcurrent()

import os
from itertools import imap
import json
import gzip
import datetime
from cStringIO import StringIO
from collections import namedtuple, defaultdict

import pymysql
from pymysql.cursors import DictCursor
from threading import local

import flask
import re
import time
import jinja2
from jinja2 import evalcontextfilter, Markup, escape, Environment


SEP = b"<!--recent_commented_articles-->"

config = json.load(open('../config/hosts.json'))
print config


def compress(b):
    s = StringIO()
    f = gzip.GzipFile(None, 'wb', 9, fileobj=s)
    f.write(b)
    f.flush()
    return s.getvalue()

def CL(d): return ('Content-Length', str(len(d)))

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

# UltraMySQL シンプルな insert や update クエリを投げるには十分だけど、
# lastrowid とか取れないのであんまり使えない。
# const char *_host, int _port, const char *_username, const char *_password, const char *_database, int _autoCommit, const char *_charset*/
#import umysql
#def get_ucon():
#    host = str(config['servers']['database'][0])
#    con = umysql.Connection()
#    con.connect(host, 3306, 'isuconapp', 'isunageruna', 'isucon', 1, 'utf8')
#    return con

app = flask.Flask(__name__)

jinja_env = Environment(loader=jinja2.FileSystemLoader('views'))

def render(template, **params):
    params['host'] = '' ## TODO
    return jinja_env.get_template(template).render(**params)

_recent_commented_articles = []

def fetch_recent_commented_articles():
    global _recent_commented_articles
    cur = db.con.cursor()
    cur.execute(
            'SELECT a.id FROM comment c INNER JOIN article a ON c.article = a.id '
            'GROUP BY a.id ORDER BY MAX(c.created_at) DESC LIMIT 10')
    for row in cur:
        _recent_commented_articles.append(row[0])


Article = namedtuple('Article', "id title body created_at")
_all_articles = {}
_recent_articles = []

def fetch_articles():
    cur = db.con.cursor()
    cur.execute('SELECT id,title,body,created_at FROM article')
    for article in imap(Article._make, cur):
        _all_articles[article.id] = article
    keys = _all_articles.keys()
    keys.sort(reverse=True)
    _recent_articles[:] = keys[:10]

def get_recent_articles():
    return [_all_articles[k] for k in _recent_articles]

Comment = namedtuple('Comment', "id article name body created_at")
_all_comments = defaultdict(list)

def fetch_comments():
    con = db.con
    cur = con.cursor()
    cur.execute("SELECT id, article, name, body, created_at FROM comment ORDER BY id")
    for comment in imap(Comment._make, cur):
        _all_comments[comment.article].append(comment)

#def ufetch_comments():
#    con = get_ucon()
#    res = con.query("SELECT id, article, name, body, created_at FROM comment ORDER BY id")
#    for comment in map(Comment._make, res.rows):
#        _all_comments[comment.article].append(comment)

def get_recent_commented_articles():
    return [_all_articles[id] for id in _recent_commented_articles]


_recent_commented_articles_cache = b''
def render_recent_commented_articles():
    global _recent_commented_articles_cache
    _recent_commented_articles_cache = render(
            'recent_article.jinja',
            recent_commented_articles = get_recent_commented_articles(),
            )

_index_page_cache = []

def render_index():
    global _index_page_cache
    index = render("index.jinja",
        articles=get_recent_articles(),
        )
    _index_page_cache = index.split(SEP)


@app.route('/')
def index():
    return _recent_commented_articles_cache.join(
            _index_page_cache)


_article_page_cache = {}

@app.route('/article/<int:articleid>')
def article(articleid):
    return _recent_commented_articles_cache.join(_article_page_cache[articleid])

def render_article(articleid):
    article_page = render('article.jinja',
        article=_all_articles[articleid],
        comments=_all_comments[articleid],
        )
    _article_page_cache[articleid] = article_page.split(SEP)

@app.route('/post', methods=('GET', 'POST'))
def post():
    if flask.request.method == 'GET':
        page = render("post.jinja")
        return page.replace(SEP, _recent_commented_articles_cache)
    title = flask.request.form['title']
    body = flask.request.form['body']
    con = db.con
    cur = con.cursor()
    cur.execute("INSERT INTO article SET title=%s, body=%s", (title, body))
    id = cur.lastrowid
    con.commit()
    _all_articles[id] = Article(id, title, body, datetime.datetime.now())
    render_article(id)
    return flask.redirect('/')

@app.route('/comment/<int:articleid>', methods=['POST'])
def comment(articleid):
    form = flask.request.form
    name = form['name']
    body = form['body']

    con = db.con
    cur = con.cursor()
    cur.execute("INSERT INTO comment SET article=%s, name=%s, body=%s",
                (articleid, form['name'], form['body'])
                )
    con.commit()
    _all_comments[articleid].append(
            Comment(cur.lastrowid, articleid, name, body, datetime.datetime.now()))
    if articleid in _recent_commented_articles:
        _recent_commented_articles.remove(articleid)
    else:
        _recent_commented_articles.pop()
    _recent_commented_articles.insert(0, articleid)
    render_recent_commented_articles()
    render_article(articleid)
    return flask.redirect('/')


_static = {}
_page_cache = {}


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
            _static[prefix + os.path.relpath(p, scan_dir)] = (
                    [('Content-Length', str(len(data))),
                     ('Content-Type', content_type),
                     ], data)
    for k in _static.keys():
        print "static:", k

# snippets:
#if 'gzip' in env.get('HTTP_ACCEPT_ENCODING', ''):

def static_middleware(app):
    u"""静的ファイルを Flask をショートカットして _static から転送する."""
    def get_cache(env, start):
        path = env['PATH_INFO']
        if env['REQUEST_METHOD'] == 'GET' and path in _static:
            head, body = _static[path]
            start("200 OK", head)
            return (body,)
        return app(env, start)
    return get_cache

def prepare_pages():
    print "fetch articles"
    fetch_articles()
    print "fetch comments"
    fetch_comments()
    print "calculate recent commented articles."
    fetch_recent_commented_articles()

    print "rendering index."
    render_index()
    print "rendering sidebar."
    render_recent_commented_articles()
    for k in _all_articles.iterkeys():
        print "rendering article:", k
        render_article(k)

def sleep(secs):
    t = time.time() + secs
    while 1:
        meinheld.schedule_call(1, greenlet.getcurrent().switch)
        mein_greenlet.switch()
        if time.time() > t:
            break

def prepare():
    prepare_static('../staticfiles', '/')
    prepare_pages()

app.wsgi_app = static_middleware(app.wsgi_app)

if __name__ == '__main__':
    #app.run(host='0.0.0.0', port=5000)
    prepare()
    app.run(debug=True)
    #import meinheld
    #meinheld.set_access_logger(None)
    #meinheld.set_backlog(128)
    #meinheld.set_keepalive(0)
    #meinheld.listen(('0.0.0.0', 5000))
    #meinheld.run(static_middleware(app.wsgi_app))
