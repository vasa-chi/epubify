import shutil
from bs4 import BeautifulSoup
import urllib2
import re
from fuzzywuzzy import process
import gevent
import mwclient
import wikimarkup
import epub
import tempfile
import os
from mwclient import page as mwpage

def one_time(func):
  arguments = dict()

  def newfunc(arg, *args, **kwargs):
    if arg not in arguments:
      res = func(arg, *args, **kwargs)
      arguments[arg] = res
      return res
    else:
      return arguments[arg]

  return newfunc


def file_write(text):
  with open('output.txt', 'w') as f:
    f.write(text)


def input_yn(prompt=None):
  while True:
    res = raw_input("{0}[y/n] ".format(prompt))
    if res == 'y':
      return True
    elif res == 'n':
      return False
    else:
      print('please use y or n')


def get_page(site, page_name):
  page = site.Pages[page_name]
  while page.redirect:
    text = page.edit().encode('utf-8')
    link = re.match(r'#REDIRECT \[\[(.+?)\]\]', text).group(1)
    page = site.Pages[link]
  return page


def choose_novel(ln_list):
  while True:
    res = raw_input(u'Light novel name: ')
    choice = process.extractOne(res.strip(), map(lambda x: x[1], ln_list))
    if choice and choice[1] > 70:
      print(u'Assuming light novel: {0}'.format(choice[0]))
      if input_yn(u'Is that the right novel?'):
        return filter(lambda ln: ln[1] == choice[0], ln_list)[0]
    else:
      print(u'Novel for query "{0}" was not found'.format(res))


def choose_volume(vol_list):
  while True:
    res = raw_input(u'Volume name: ')
    choice = process.extractOne(res.strip(), map(lambda x: x[0], vol_list))
    if choice and choice[1] > 50:
      print(u'Assuming volume: {0}'.format(choice[0]))
      if input_yn(u'Is that the right volume?'):
        return filter(lambda x: x[0] == choice[0], vol_list)[0]
    else:
      print(u'Volume for query "{0}" was not found'.format(res))


def export_book(site, page, cover=None):
  image_jobs = []

  def clean_page(page_text):
    refr = re.compile(r'(&lt;ref.+?&lt;/ref&gt;)', re.DOTALL)
    noinclude = re.compile(r'<p>&lt;noinclude&gt;.+?&lt;/noinclude&gt;.+?</p>', re.DOTALL)
    noinclude_safe = re.compile(r'&lt;noinclude&gt;.+?&lt;/noinclude&gt;.+?</p>', re.DOTALL)
    tr_note = re.compile(r'<h2\ id\=\"w\_translator.+?references\ group=.+?</p>', re.DOTALL)
    empty_p = re.compile(r'<p>\w*?</p>')

    page_text = re.sub(refr, '', page_text)
    page_text = re.sub(noinclude, '', page_text)
    page_text = re.sub(noinclude_safe, '</p>', page_text)
    page_text = re.sub(tr_note, '', page_text)
    page_text = re.sub(empty_p, '', page_text)
    return page_text

  @one_time
  def download_image(image):
    try:
      print('Downloading image {0}'.format(image))
      i = site.Images[image]
      _, path = tempfile.mkstemp()
      with open(path, 'wb') as out:
        shutil.copyfileobj(i.download(), out)
      print('Finished downloading image {0}'.format(image))
      return path, image
    except urllib2.URLError:
      print('ERROR! retrying...')
      return download_image(image)

  def put_images(page_text):
    def replace_image(match):
      image = match.group(1)
      image = mwpage.Page.normalize_title(image)
      image_jobs.append(gevent.spawn(download_image, image))
      return '<img src="{0}" alt="{0}"/>'.format(image)

    images = re.compile(r'\[\[Image:(.+?)\|.+?\]\]', re.DOTALL | re.IGNORECASE)
    return re.sub(images, replace_image, page_text)

  def save_page(page):
    markup = wikimarkup.parse(page.edit().encode('utf-8'), showToc=False)
    markup = clean_page(markup)
    markup = put_images(markup)

    return page, markup

  def save_illustrations_page(page):
    def insert_images(markup):
      def replace_image(match):
        image = match.group(1)
        image = mwpage.Page.normalize_title(image)
        image_jobs.append(gevent.spawn(download_image, image))
        return '<img src={0} alt="{0}/>'.format(image)

      images = re.compile(r'Image\:(.+?)(?:\n|\|.+)', re.IGNORECASE)
      markup = re.sub(images, replace_image, markup)
      return markup

    markup = wikimarkup.parse(page.edit().encode('utf-8'), showToc=False)
    markup = clean_page(markup)
    markup = re.sub(r'&lt;gallery&gt;', '', markup)
    markup = re.sub(r'&lt;/gallery&gt;', '', markup)
    markup = insert_images(markup)
    return page, markup

  if cover:
    image_jobs.append(gevent.spawn(download_image, cover))

  itemr = re.compile(r'\{\{\:(.+?)(?:\|.*?)?}}')

  text = page.edit().encode('utf-8')

  toc = itemr.findall(text)
  jobs = [gevent.spawn(get_page, site, p) for p in toc]
  gevent.joinall(jobs)

  pages = [gevent.spawn(save_illustrations_page, jobs[0].value)]
  pages.extend([gevent.spawn(save_page, book_page) for book_page in (job.value for job in jobs[1:])])

  gevent.joinall(pages)
  gevent.joinall(image_jobs)

  image_list = [job.value for job in image_jobs]

  book = epub.EpubBook()
  book.setTitle(page.name)
  book.setLang('en-US')
  book.addCreator('baka-tsuki.org')

  if cover:
    book.addCover(cover)

  image_list = set(image_list)
  for path, img in image_list:
    book.addImage(path, img)

  for book_page, markup in (book_page.value for book_page in pages):
    element = book.addHtml('', book_page.name + '.html', markup)
    book.addSpineItem(element)

  book_dir = tempfile.mkdtemp()
  book.createBook(book_dir)
  book.createArchive(book_dir, u'{0}.epub'.format(page.name))

  for path, _ in image_list:
    os.remove(path)

  shutil.rmtree(book_dir)


def main():
  bt = urllib2.urlopen('http://www.baka-tsuki.org/project/index.php?title=Main_Page')
  bt = BeautifulSoup(bt, 'lxml')

  def parse_light_novels(ln_href):
    ln_regex = re.compile(r'/project/index\.php\?title=(.+)')
    return ln_regex.findall(ln_href.get('href'))[0], ln_href.get_text()

  light_novels = bt.select('#p-Light_Novels li > a')
  light_novels = map(parse_light_novels, light_novels)

  novel = choose_novel(light_novels)

  site = mwclient.Site('www.baka-tsuki.org', '/project/')
  page = get_page(site, novel[0])

  page_text = page.edit().encode('utf-8')

  full_text = re.compile(r'===(.+?)\s*?\(\[\[(.+?)\|Full Text\]\]')

  volumes = full_text.findall(page_text)
  print(u'Full volumes:')
  for name, _ in volumes:
    print name

  volume = choose_volume(volumes)

  volume_page = get_page(site, volume[1])

  export_book(site, volume_page)

if __name__ == '__main__':
  main()
