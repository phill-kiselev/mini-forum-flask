from flask import render_template, flash, redirect, session, url_for, request, g
from flask_login import login_user, logout_user, current_user, login_required
from app import app, db, lm, oid
from .forms import LoginForm, LoginForm2, EditForm, PostForm, SearchForm, RegisterForm
from .models import User, ROLE_USER, ROLE_ADMIN, Post
from datetime import datetime
from config import POSTS_PER_PAGE, MAX_SEARCH_RESULTS
from .emails import follower_notification
from guess_language.guess_language import guessLanguage
from flask import jsonify
from .translate import microsoft_translate


@app.route('/user/<nickname>/popup')
@login_required
def user_popup(nickname):
    user = User.query.filter_by(nickname=nickname).first_or_404()
    return render_template('user_popup.html', user=user)

@app.route('/translate', methods = ['POST'])
@login_required
def translate():
    return jsonify({ 
        'text': microsoft_translate(
            request.form['text'], 
            request.form['sourceLang'], 
            request.form['destLang']) })

@app.before_request
def before_request():
    g.user = current_user
    if g.user.is_authenticated:
        g.user.last_seen = datetime.utcnow()
        db.session.add(g.user)
        db.session.commit()
        g.search_form = SearchForm()
    
@lm.user_loader
def load_user(id):
    return User.query.get(int(id))
    
@app.route('/', methods = ['GET', 'POST'])
@app.route('/index', methods = ['GET', 'POST'])
@app.route('/index/<int:page>', methods = ['GET', 'POST'])
@login_required
def index(page = 1):
    form = PostForm()
    if form.validate_on_submit():
        language = guessLanguage(form.post.data)
        if language == 'UNKNOWN' or len(language) > 5:
              language = 'en'
        post = Post(body = form.post.data, timestamp = datetime.utcnow(), author = g.user, language = language)
        db.session.add(post)
        db.session.commit()
        flash('Your post is now live!')
        return redirect(url_for('index'))
    posts = g.user.followed_posts().paginate(page, POSTS_PER_PAGE, False)
    return render_template('index.html',
        title = 'Home',
        form = form,
        posts = posts)

@app.route('/follow/<nickname>')
@login_required
def follow(nickname):
    user = User.query.filter_by(nickname = nickname).first()
    if user == None:
        flash('User ' + nickname + ' not found.')
        return redirect(url_for('index'))
    if user == g.user:
        flash('You can\'t follow yourself!')
        return redirect(url_for('user', nickname = nickname))
    u = g.user.follow(user)
    if u is None:
        flash('Cannot follow ' + nickname + '.')
        return redirect(url_for('user', nickname = nickname))
    db.session.add(u)
    db.session.commit()
    flash('You are now following ' + nickname + '!')
    follower_notification(user, g.user)
    return redirect(url_for('user', nickname = nickname))

@app.route('/unfollow/<nickname>')
@login_required
def unfollow(nickname):
    user = User.query.filter_by(nickname = nickname).first()
    if user == None:
        flash('User ' + nickname + ' not found.')
        return redirect(url_for('index'))
    if user == g.user:
        flash('You can\'t unfollow yourself!')
        return redirect(url_for('user', nickname = nickname))
    u = g.user.unfollow(user)
    if u is None:
        flash('Cannot unfollow ' + nickname + '.')
        return redirect(url_for('user', nickname = nickname))
    db.session.add(u)
    db.session.commit()
    flash('You have stopped following ' + nickname + '.')
    return redirect(url_for('user', nickname = nickname))

@app.route('/register', methods = ['GET', 'POST'])
@oid.loginhandler
def register():
  if g.user is not None and g.user.is_authenticated:
      return redirect(url_for('index'))
  form = RegisterForm()
  if form.validate_on_submit():
      session['remember_me'] = form.remember_me.data
      u = User(nickname=form.nickname.data, email=form.mail.data, role=ROLE_USER)
      db.session.add(u)
      db.session.commit()
      # make the user follow him/herself
      db.session.add(u.follow(u))
      db.session.commit()
      login_user(u, remember = form.remember_me.data)
      flash('Registration - success!')
      return redirect(url_for('index'))
  return render_template('register.html', 
      title = 'Sign Up',
      form = form)

@app.route('/login', methods = ['GET', 'POST'])
@oid.loginhandler
def login():
  if g.user is not None and g.user.is_authenticated:
      return redirect(url_for('index'))
  form1 = LoginForm()
  form2 = LoginForm2()
  if form1.validate_on_submit():
      session['remember_me'] = form1.remember_me.data
      return oid.try_login(form1.openid.data, ask_for = ['nickname', 'email'])
  if form2.validate_on_submit():
      session['remember_me'] = form2.remember_me.data
      user = User.query.filter_by(nickname = form2.nickname.data).first()
      if user.email == form2.mail.data:
      #u = User(nickname=form2.nickname.data, email=form2.mail.data, role=ROLE_USER)
      #db.session.add(u)
      #db.session.commit()
      # make the user follow him/herself
      #db.session.add(u.follow(u))
      #db.session.commit()
        login_user(user, remember = form2.remember_me.data)
        flash('Log in - success!')
        return redirect(url_for('index'))
  return render_template('login.html', 
      title = 'Sign In',
      form = form1,
      form2 = form2,
      providers = app.config['OPENID_PROVIDERS'])

@oid.after_login
def after_login(resp):
    if resp.email is None or resp.email == "":
        flash('Invalid login. Please try again.')
        return redirect(url_for('login'))
    user = User.query.filter_by(email = resp.email).first()
    if user is None:
        nickname = resp.nickname
        if nickname is None or nickname == "":
            nickname = resp.email.split('@')[0]
        nickname = User.make_unique_nickname(nickname)
        user = User(nickname = nickname, email = resp.email, role = ROLE_USER)
        db.session.add(user)
        db.session.commit()
        # make the user follow him/herself
        db.session.add(user.follow(user))
        db.session.commit()
    remember_me = False
    if 'remember_me' in session:
        remember_me = session['remember_me']
        session.pop('remember_me', None)
    login_user(user, remember = remember_me)
    return redirect(request.args.get('next') or url_for('index'))

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/user/<nickname>')
@app.route('/user/<nickname>/<int:page>')
@login_required
def user(nickname, page = 1):
    user = User.query.filter_by(nickname = nickname).first()
    if user == None:
        flash('User ' + nickname + ' not found.')
        return redirect(url_for('index'))
    posts = user.posts.paginate(page, POSTS_PER_PAGE, False)
    return render_template('user.html',
        user = user,
        posts = posts)

@app.route('/edit', methods = ['GET', 'POST'])
@login_required
def edit():
    form = EditForm(g.user.nickname)
    if form.validate_on_submit():
        g.user.nickname = form.nickname.data
        g.user.about_me = form.about_me.data
        db.session.add(g.user)
        db.session.commit()
        flash('Your changes have been saved.')
        return redirect(url_for('edit'))
    else:
        form.nickname.data = g.user.nickname
        form.about_me.data = g.user.about_me
    return render_template('edit.html',
        form = form)

@app.route('/search', methods = ['POST'])
@login_required
def search():
    if not g.search_form.validate_on_submit():
        return redirect(url_for('index'))
    return redirect(url_for('search_results', query = g.search_form.search.data))

@app.route('/search_results/<query>')
@login_required
def search_results(query):
    results = Post.query.whoosh_search(query, MAX_SEARCH_RESULTS).all()
    return render_template('search_results.html',
        query = query,
        results = results)

@app.errorhandler(404)
def not_found_error(error):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return render_template('500.html'), 500