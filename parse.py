import gevent
import mwclient
import re
import string
import epub
import shutil
import wikimarkup

site = mwclient.Site('www.baka-tsuki.org', '/project/')
page = site.Pages['Campione!:Volume_1']
text = page.edit().encode('utf-8')

cover = site.Images['Campione_Vol.01_003.jpg']

def get_page(page):
  return site.Pages[page]

refr = re.compile(r'(&lt;ref\ group=.+&lt;/ref&gt;)', re.DOTALL)
noinclude = re.compile(r'<p>&lt;noinclude&gt;.+?&lt;/noinclude&gt;.+?</p>', re.DOTALL)
tr_note = re.compile(r'<h2\ id\=\"w\_translator.+?references\ group=.+?</p>', re.DOTALL)

def clean_page(page_text):
  page_text = re.sub(refr, '', page_text)
  page_text = re.sub(noinclude, '', page_text)
  page_text = re.sub(tr_note, '', page_text)
  return page_text

images = re.compile(r'<p>\[\[Image:(.+?)\|.+?\]\].+?</p>', re.DOTALL)

def download_image(image):
  i = site.Images[image]
  with open(image, 'wb') as out:
    shutil.copyfileobj(i.download(), out)
  return i.name

image_list = []

def put_images(page_text):
  def replace_image(match):
    download_image(match.group(1))
    image_list.append(match.group(1))
    return '<img src="{0}" alt="{0}"/>'.format(match.group(1))

  return re.sub(images, replace_image, page_text)


def save_page(page):
  markup = ''
  with open(page.name + '.html', 'w') as f:
    markup = wikimarkup.parse(page.edit().encode('utf-8'), showToc=False)
    markup = clean_page(markup)
    markup = put_images(markup)

    f.write(markup)
  return (page, markup)

p = string.punctuation.replace(']', '\]').replace('|', '')
itemr = re.compile(r'{{\:([\w!"#$%&\'()*+,-./:;<=>?@[\]^_`{}~]+)\|?(.*)}}')

toc = ((page, name) for (page, name) in itemr.findall(text))
jobs = [gevent.spawn(get_page, p) for (p, name) in toc]
gevent.joinall(jobs)

pages = [gevent.spawn(save_page, page) for page in (job.value for job in jobs[1:])]
gevent.joinall(pages)

book = epub.EpubBook()
book.setTitle('Campione!:Volume_1')

cover = book.addCover('Campione_Vol.01_003.jpg')

for img in image_list:
  book.addImage(img, img)

for page, markup in (page.value for page in pages):
  element = book.addHtml(page.name + '.html', page.name + '.html', markup)
  book.addSpineItem(element)

book.createBook(r'book')
book.createArchive(r'book', r'book.epub')
