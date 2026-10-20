#!/usr/bin/env python3
"""Generate the blog and static site. Python 3.11+, no third-party packages."""
from pathlib import Path, PurePosixPath
from html import escape, unescape
from html.parser import HTMLParser
from urllib.parse import urlparse, parse_qs, unquote, quote
from datetime import date, datetime
import argparse, json, re, shutil, hashlib
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
ALLOWED = {'p','h2','h3','h4','h5','h6','ul','ol','li','strong','em','b','i','u','s','blockquote','a','img','br','hr','pre','code','table','thead','tbody','tr','th','td','figure','figcaption','sup','sub'}
VOID = {'img','br','hr'}
BLOCKED = {'script','style','iframe','object','embed','svg','math','template'}

def text(value):
    return escape(str(value), quote=True)

def local_url(value, prefix):
    """Resolve site-local paths from the site root, including /repo Pages hosting."""
    value = str(value).strip()
    if not value: return ''
    if any(ord(c) < 32 for c in value) or '\\' in value: raise ValueError('Invalid URL characters')
    parsed = urlparse(value)
    if parsed.scheme:
        if parsed.scheme not in ('https', 'http') or not parsed.netloc: raise ValueError('Use an HTTPS or site-local URL')
        return value
    if value.startswith('//'): raise ValueError('Protocol-relative URLs are not supported')
    if value.startswith('#'): return value
    clean = parsed.path.lstrip('/')
    if '..' in PurePosixPath(unquote(clean)).parts: raise ValueError('Use a path from the site root, without ../')
    return prefix + value.lstrip('/')

class SafeHTML(HTMLParser):
    def __init__(self, prefix):
        super().__init__(convert_charrefs=True)
        self.prefix, self.result, self.blocked, self.stack = prefix, [], [], []
    def handle_starttag(self, tag, attrs):
        if self.blocked:
            if tag in BLOCKED: self.blocked.append(tag)
            return
        if tag in BLOCKED:
            if tag != 'embed': self.blocked.append(tag)
            return
        if tag not in ALLOWED: return
        output=[]
        for key,value in attrs:
            value = value or ''
            if tag == 'a' and key == 'href':
                try:
                    if value.startswith(('mailto:', 'tel:')):
                        if any(ord(c)<32 for c in value): continue
                        url=value
                    else: url=local_url(value,self.prefix)
                    output.append(('href',url))
                except ValueError: pass
            elif tag == 'img' and key == 'src':
                try: output.append(('src',local_url(value,self.prefix)))
                except ValueError: pass
            elif key in ('title',) or (tag == 'img' and key == 'alt'):
                output.append((key,value))
        if tag == 'img': output.extend([('loading','lazy'),('decoding','async')])
        self.result.append('<'+tag+''.join(f' {k}="{text(v)}"' for k,v in output)+'>')
        if tag not in VOID: self.stack.append(tag)
    def handle_endtag(self,tag):
        if self.blocked:
            if tag in self.blocked:
                index=len(self.blocked)-1-self.blocked[::-1].index(tag)
                del self.blocked[index:]
            return
        if tag in self.stack:
            while self.stack:
                item=self.stack.pop(); self.result.append(f'</{item}>')
                if item==tag: break
    def handle_data(self,data):
        if not self.blocked: self.result.append(escape(data))
    def handle_startendtag(self,tag,attrs):
        self.handle_starttag(tag,attrs)
        if tag not in VOID: self.handle_endtag(tag)
    def finish(self):
        while self.stack: self.result.append('</'+self.stack.pop()+'>')
        return ''.join(self.result)

def body_html(value,prefix):
    parser=SafeHTML(prefix); parser.feed(value); parser.close(); return parser.finish()

def render(name,values):
    template=(ROOT/'templates'/f'{name}.html').read_text()
    return re.sub(r'\{\{(\w+)\}\}',lambda m:str(values[m[1]]),template)

def page(title,description,main,prefix,seo_head=""):
    """Title is already the complete search title, with branding handled by metadata()."""
    values={'seo_head':seo_head,'root':prefix,'title':text(title),'description':text(description),'main':main, 'css_version':hashlib.sha256((ROOT/'CSS/SHR_Blog.css').read_bytes()).hexdigest()[:12], 'js_version':hashlib.sha256((ROOT/'JS/SHR_Blog.js').read_bytes()).hexdigest()[:12]}
    values['header']=render('header',values); values['footer']=render('footer',values)
    return render('page',values)

def video_source(value):
    parsed=urlparse(value)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Video URL must be HTTPS')
    host=parsed.hostname.lower()
    if host in ('youtube.com','www.youtube.com','m.youtube.com','youtube-nocookie.com','www.youtube-nocookie.com','youtu.be'):
        parts=parsed.path.strip('/').split('/')
        if host=='youtu.be': ident=parts[0]
        elif parts[0] in ('embed','shorts','live') and len(parts)>1: ident=parts[1]
        else: ident=parse_qs(parsed.query).get('v',[''])[0]
        if not re.fullmatch(r'[A-Za-z0-9_-]{11}',ident): raise ValueError('Paste a valid YouTube video URL')
        return 'embed','https://www.youtube-nocookie.com/embed/'+ident
    if host in ('vimeo.com','www.vimeo.com','player.vimeo.com'):
        parts=parsed.path.strip('/').split('/')
        numbers=[p for p in parts if p.isdigit()]
        if not numbers: raise ValueError('Paste a valid Vimeo video URL')
        ident=numbers[0]
        embed='https://player.vimeo.com/video/'+ident
        private_hash=parse_qs(parsed.query).get('h',[''])[0]
        if not private_hash and len(parts)>1 and parts[-1]!=ident and re.fullmatch(r'[A-Za-z0-9]+',parts[-1]): private_hash=parts[-1]
        if private_hash:
            if not re.fullmatch(r'[A-Za-z0-9]+',private_hash): raise ValueError('Invalid Vimeo privacy hash')
            embed+='?h='+private_hash
        return 'embed',embed
    if parsed.path.lower().endswith(('.mp4','.webm')): return 'file',value
    raise ValueError('Video must be a YouTube, Vimeo, HTTPS MP4, or HTTPS WebM URL')

def video_html(post):
    value=post.get('video_url','')
    if not value: return ''
    kind,url=video_source(value)
    if kind=='embed':
        player=f'<iframe src="{text(url)}" title="{text(post["title"])}" loading="lazy" allow="fullscreen; picture-in-picture" referrerpolicy="strict-origin-when-cross-origin" allowfullscreen></iframe>'
    else:
        player=f'<video controls playsinline preload="metadata" aria-label="{text(post["title"])}"><source src="{text(url)}" type="video/{"webm" if urlparse(url).path.lower().endswith(".webm") else "mp4"}">Your browser cannot play this video. <a href="{text(url)}">Open the video</a>.</video>'
    caption=post.get('video_caption','')
    return '<figure class="blog-video"><div class="blog-player">'+player+'</div>'+(f'<figcaption>{text(caption)}</figcaption>' if caption else '')+'</figure>'

def cover(post,prefix,large=False):
    if post.get('cover'):
        return f'<img src="{text(local_url(post["cover"],prefix))}" alt="{text(post.get("cover_alt",""))}" loading="lazy">'
    icon='▷' if post.get('video_url') else '↗'
    return f'<div class="blog-cover-art" aria-hidden="true"><span class="blog-art-label">SISKIYOU HR<br>SOLUTIONS</span><span class="blog-art-icon">{icon}</span><span class="blog-art-mountain"></span></div>'

def keyword_tags(value):
    if value is None: return []
    if not isinstance(value,list) or any(not isinstance(tag,str) for tag in value):
        raise ValueError('Keyword tags must be a list of text values')
    result=[]; seen=set()
    for tag in value:
        tag=' '.join(tag.split())
        if tag and tag.casefold() not in seen:
            seen.add(tag.casefold()); result.append(tag)
    return result

def tag_links(post,prefix=''):
    links=''.join(f'<li><a href="{prefix}SHR_Blog.html?q={text(quote(tag,safe=""))}#latest" aria-label="View posts tagged {text(tag)}">{text(tag)}</a></li>' for tag in post.get('tags',[]))
    return f'<ul class="blog-tags" aria-label="Post keywords">{links}</ul>' if links else ''

def search_text(post):
    body=unescape(re.sub(r'<[^>]*>',' ',body_html(post.get('body',''),'')))
    return ' '.join([post['title'],post['excerpt'],post['category'],post['author'],body,post.get('transcript','')]+post.get('tags',[]))

def card(post):
    fmt='video' if post.get('video_url') else 'article'
    label='Watch & read' if fmt=='video' else 'Read article'
    meta=f'{post["display_date"]} · {"Video" if fmt=="video" else "Article"}'
    return f'''<article class="blog-card" data-format="{fmt}" data-search="{text(search_text(post))}"><a class="blog-card-cover" href="blog/{post['slug']}/" tabindex="-1" aria-hidden="true">{cover(post,'')}</a><div class="blog-card-content"><h3><a href="blog/{post['slug']}/">{text(post['title'])}</a></h3><p class="blog-card-excerpt">{text(post['excerpt'])}</p>{tag_links(post)}<p class="blog-meta">{text(meta)}</p><a class="blog-read-link" href="blog/{post['slug']}/" aria-label="{label}: {text(post['title'])}">{label} <span aria-hidden="true">↗</span></a></div></article>'''

DEFAULT_SITE = {
    'site_url': 'https://www.siskiyouhr.com',
    'site_name': 'Siskiyou HR Solutions',
    'blog_title': 'Blog | Siskiyou HR Solutions',
    'blog_description': 'Articles, videos, and practical workplace perspectives from Siskiyou HR Solutions.',
    'social_image': '',
    'social_image_alt': '',
}

def load_site():
    path=ROOT/'content/site.json'
    site=dict(DEFAULT_SITE)
    if path.exists(): site.update(json.loads(path.read_text()))
    for key in DEFAULT_SITE:
        if not isinstance(site.get(key),str): raise ValueError(f'Site setting {key} must be text')
    site['site_url']=site['site_url'].rstrip('/')
    parsed=urlparse(site['site_url'])
    if (parsed.scheme!='https' or not parsed.hostname or parsed.query or parsed.fragment or parsed.username or parsed.password
            or re.search(r'[\s\\]',site['site_url']) or '..' in PurePosixPath(unquote(parsed.path)).parts):
        raise ValueError('site_url must be the public HTTPS site URL, optionally with a repository path')
    return site

def absolute_url(value,site):
    value=local_url(value,'')
    if not urlparse(value).scheme: value=site['site_url']+'/'+value
    return quote(value,safe=":/?&=%#@+;,")

def seo_fields(post):
    value=post.get('seo') or {}
    if not isinstance(value,dict): raise ValueError('seo must be an object')
    for key in ('title','description','social_image','social_image_alt','modified','video_thumbnail','video_upload_date'):
        if value.get(key) is not None and not isinstance(value[key],str): raise ValueError(f'seo.{key} must be text')
    if value.get('noindex') is not None and not isinstance(value['noindex'],bool): raise ValueError('seo.noindex must be true or false')
    if value.get('modified'):
        modified=date.fromisoformat(value['modified'])
        if modified < date.fromisoformat(post['date']): raise ValueError('Updated date cannot precede the display date')
    if value.get('video_upload_date'):
        uploaded=datetime.fromisoformat(value['video_upload_date'].replace('Z','+00:00'))
        if uploaded.tzinfo is None: raise ValueError('Video upload date must include a timezone')
    return value

def metadata(site,path,post=None,demo=False):
    seo=seo_fields(post) if post else {}
    title=(seo.get('title') or '').strip() or (post['title']+' | '+site['site_name'] if post else site['blog_title'])
    description=(seo.get('description') or '').strip() or (post['excerpt'] if post else site['blog_description'])
    canonical=absolute_url(path,site)
    if seo.get('social_image'):
        image,image_alt=seo['social_image'],seo.get('social_image_alt','')
    elif post and post.get('cover'):
        image,image_alt=post['cover'],post.get('cover_alt','')
    else:
        image,image_alt=site['social_image'],site['social_image_alt']
    noindex=demo or seo.get('noindex') is True
    head=[f'<link rel="canonical" href="{text(canonical)}">',
          f'<meta name="robots" content="{"noindex, follow" if noindex else "index, follow, max-image-preview:large"}">']
    tags=[('property','og:type','article' if post else 'website'),
          ('property','og:site_name',site['site_name']),('property','og:title',title),
          ('property','og:description',description),('property','og:url',canonical),
          ('name','twitter:card','summary_large_image' if image else 'summary'),
          ('name','twitter:title',title),('name','twitter:description',description)]
    if image:
        image=absolute_url(image,site)
        tags.extend([('property','og:image',image),('name','twitter:image',image)])
        if image_alt: tags.extend([('property','og:image:alt',image_alt),('name','twitter:image:alt',image_alt)])
    if post:
        tags.append(('property','article:published_time',post['date']))
        if seo.get('modified'): tags.append(('property','article:modified_time',seo['modified']))
        author={'@type':'Organization' if post['author']==site['site_name'] else 'Person','name':post['author']}
        schema={'@context':'https://schema.org','@type':'BlogPosting','headline':post['title'],
                'description':description,'url':canonical,'mainEntityOfPage':{'@type':'WebPage','@id':canonical},
                'datePublished':post['date'],'author':author,
                'publisher':{'@type':'Organization','name':site['site_name'],'url':site['site_url']+'/'}}
        if seo.get('modified'): schema['dateModified']=seo['modified']
        if post.get('cover'): schema['image']=[absolute_url(post['cover'],site)]
        # Only declare VideoObject when its required thumbnail and upload date are supplied.
        if post.get('video_url') and seo.get('video_thumbnail') and seo.get('video_upload_date'):
            kind,url=video_source(post['video_url'])
            schema['video']={'@type':'VideoObject','name':post['title'],'description':post['excerpt'],
                             'thumbnailUrl':[absolute_url(seo['video_thumbnail'],site)],
                             'uploadDate':seo['video_upload_date'],
                             'embedUrl' if kind=='embed' else 'contentUrl':url}
            if post.get('transcript'): schema['video']['transcript']=post['transcript']
        # Escape '<' so editor-entered text cannot close the JSON-LD script element.
        encoded=json.dumps(schema,ensure_ascii=True).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
        head.append('<script type="application/ld+json">'+encoded+'</script>')
    head.extend(f'<meta {attr}="{key}" content="{text(value)}">' for attr,key,value in tags)
    return title,description,'\n'.join(head)

def write_sitemap(output,site,posts,demo):
    namespace='http://www.sitemaps.org/schemas/sitemap/0.9'
    ET.register_namespace('',namespace)
    tree=ET.Element('{'+namespace+'}urlset')
    urls=[] if demo else [(absolute_url('SHR_Blog.html',site),None)]
    if not demo:
        for post in posts:
            seo=seo_fields(post)
            if not seo.get('noindex'):
                urls.append((absolute_url('blog/'+post['slug']+'/',site),seo.get('modified') or post['date']))
    for url,modified in urls:
        entry=ET.SubElement(tree,'{'+namespace+'}url')
        ET.SubElement(entry,'{'+namespace+'}loc').text=url
        if modified: ET.SubElement(entry,'{'+namespace+'}lastmod').text=modified
    ET.ElementTree(tree).write(output/'blog-sitemap.xml',encoding='utf-8',xml_declaration=True)
    robots=output/'robots.txt'
    current=robots.read_text() if robots.exists() else 'User-agent: *\nAllow: /\n'
    sitemap='Sitemap: '+absolute_url('blog-sitemap.xml',site)
    # Keep existing crawl directives and the site's other sitemap declarations.
    if not demo and sitemap not in current: current=current.rstrip()+'\n\n'+sitemap+'\n'
    robots.write_text(current)

def build(output, demo=False):
    output=output.resolve()
    # Cleanup is deliberately restricted to children of this project.
    if output.parent != ROOT or output.name not in ('dist','preview'): raise ValueError('Output must be dist or preview inside this project')
    site=load_site()
    posts=[]
    for path in sorted((ROOT/'content/posts').glob('*.json')):
        post=json.loads(path.read_text())
        if not isinstance(post,dict): raise ValueError(f'{path.name}: expected a JSON object')
        if not demo and post.get('published') is not True: continue
        slug=path.stem
        if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*',slug): raise ValueError(f'{path.name}: use a lowercase hyphenated filename')
        for key in ('title','date','author','category','excerpt'):
            if not isinstance(post.get(key),str) or not post[key].strip(): raise ValueError(f'{path.name}: {key} is required')
        for key in ('body','cover','cover_alt','video_url','video_caption','transcript'):
            if post.get(key) is None: post[key]=''
            if not isinstance(post.get(key,''),str): raise ValueError(f'{path.name}: {key} must be text')
        if not post.get('body','').strip() and not post.get('video_url'): raise ValueError(f'{path.name}: add text or a video')
        date_value=date.fromisoformat(post['date'])
        seo=seo_fields(post)
        for key in ('social_image','video_thumbnail'):
            if seo.get(key): absolute_url(seo[key],site)
        if post.get('video_url'): video_source(post['video_url'])
        if post.get('cover'): local_url(post['cover'],'')
        post['tags']=keyword_tags(post.get('tags'))
        post['slug']=slug; post['display_date']=date_value.strftime('%B %d, %Y').replace(' 0',' ')
        posts.append(post)
    posts.sort(key=lambda p:(p['date'],p['slug']),reverse=True)
    if output.exists(): shutil.rmtree(output)
    output.mkdir()
    # Carry existing plain HTML site through deployment; never include CMS drafts/source.
    for file in ROOT.iterdir():
        if file.is_file() and (file.suffix.lower() in ('.html','.css','.js','.ico','.xml','.webmanifest') or file.name in ('CNAME','robots.txt')):
            shutil.copy2(file,output/file.name)
    for source in ROOT.iterdir():
        if source.is_dir() and source.name.lower() in ('css','js','images','assets','fonts','.well-known'):
            shutil.copytree(source,output/source.name,ignore=shutil.ignore_patterns('.gitkeep'))
    (output/'.nojekyll').touch()
    selected=next((p for p in posts if p.get('featured')),posts[0] if posts else None)
    featured=''
    if selected:
        fmt='Video' if selected.get('video_url') else 'Article'
        featured=f'''<section class="blog-featured" aria-labelledby="featured-heading"><a class="blog-featured-cover" href="blog/{selected['slug']}/" tabindex="-1" aria-hidden="true">{cover(selected,'',True)}</a><div class="blog-featured-content"><h2 id="featured-heading"><a href="blog/{selected['slug']}/">{text(selected['title'])}</a></h2><p>{text(selected['excerpt'])}</p><p class="blog-meta">{text(selected['display_date'])} · {text(selected['author'])}</p><a class="blog-read-link" href="blog/{selected['slug']}/">Explore this post <span aria-hidden="true">↗</span></a></div></section>'''
    empty='' if posts else '<div class="blog-empty"><h3>Good conversations start here.</h3><p>New articles and videos are on their way. In the meantime, we’d love to hear what’s on your mind.</p><a class="blog-read-link" href="SHR_Contact.html">Talk with us ↗</a></div>'
    listing=render('listing',{'root':'','featured':featured,'cards':''.join(map(card,posts)),'empty':empty})
    title,description,head=metadata(site,'SHR_Blog.html',demo=demo)
    (output/'SHR_Blog.html').write_text(page(title,description,listing,'',head))
    for post in posts:
        prefix='../../'
        values={k:text(post.get(k,'')) for k in ('category','excerpt','author')}
        values.update(tags=tag_links(post,prefix),root=prefix,post_title=text(post['title']),date=text(post['display_date']),format='Video' if post.get('video_url') else 'Article',cover=f'<div class="blog-article-cover">{cover(post,prefix)}</div>' if post.get('cover') else '',video=video_html(post),body=body_html(post.get('body',''),prefix),transcript=f'<details class="blog-transcript"><summary>Read the video transcript</summary><div>{text(post["transcript"])}</div></details>' if post.get('transcript') else '')
        seo=seo_fields(post)
        if seo.get('modified'):
            values['date']+=' · Updated '+text(date.fromisoformat(seo['modified']).strftime('%B %d, %Y').replace(' 0',' '))
        article=render('article',values)
        target=output/'blog'/post['slug']; target.mkdir(parents=True)
        title,description,head=metadata(site,'blog/'+post['slug']+'/',post,demo)
        (target/'index.html').write_text(page(title,description,article,prefix,head))
    write_sitemap(output,site,posts,demo)
    print(f'Built {len(posts)} {"demo" if demo else "published"} posts → {output}')

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--demo',action='store_true',help='Include drafts in a LOCAL DEMONSTRATION build only')
    parser.add_argument('--output',default='dist')
    args=parser.parse_args()
    build(ROOT/args.output,args.demo)
