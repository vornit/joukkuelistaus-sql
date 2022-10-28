from flask import Flask, session, redirect, url_for, escape, request, Response, render_template
import hashlib
import sys
from functools import wraps
import mysql.connector
import mysql.connector.pooling
import os
import werkzeug.exceptions
import json
from mysql.connector import errorcode
from jinja2 import Template, Environment, FileSystemLoader
import datetime
import wtforms
from wtforms import Form, BooleanField, StringField, validators, IntegerField, SelectField, widgets, SelectMultipleField, ValidationError, RadioField, DecimalField
from wtforms.validators import NumberRange
from flask_wtf import FlaskForm
from polyglot import PolyglotForm
import urllib.request

app = Flask(__name__)

app.config.update(
    SESSION_COOKIE_SAMESITE='Lax'
)

app.secret_key = '"\xf9$T\x88\xefT8[\xf1\xc4Y-r@\t\xec!5d\xf9\xcc\xa2\xaa'

with open('/home/vornit2/mysite/dbconfig.json', 'r') as f:
    dbconfig = data = json.load(f)

def auth(f):
    ''' Tämä decorator hoitaa kirjautumisen tarkistamisen ja ohjaa tarvittaessa kirjautumissivulle
    '''
    @wraps(f)
    def decorated(*args, **kwargs):
        # tässä voisi olla monimutkaisempiakin tarkistuksia mutta yleensä tämä riittää
        if not 'kirjautunut' in session:
            return redirect(url_for('kirjaudu'))
        return f(*args, **kwargs)
    return decorated

@app.route('/kirjaudu', methods=['GET', 'POST'])
def kirjaudu():

    try:
        pool=mysql.connector.pooling.MySQLConnectionPool(pool_name="tietokantayhteydet",
        pool_size=2, #PythonAnywheren ilmaisen tunnuksen maksimi on kolme
        **dbconfig
        )
        con = pool.get_connection()
        cur = con.cursor(buffered=True, dictionary=True)
    except:
        return "Yhdistäminen tietokantaan epäonnistui"

    # haetaan kirjautumiskenttien tiedot
    try:
        joukkue = request.form.get('joukkue', "").strip()
        salasana = request.form.get('salasana', "")
        valittuKisa = request.form.get('kisanimet', "")
    except:
        joukkue = ""
        salasana = ""
        valittuKisa = ""

    #haetaan kaikkien kilpailujen tiedot
    kisanimet = []
    try:
        sql = '''SELECT kisanimi, alkuaika, id
        FROM kilpailut'''
        cur.execute( sql )
        kisanimet = cur.fetchall()
        #muutetaan kisojen päivämäärät pelkiksi vuosiksi
        for i in range(len(kisanimet)):
            kisanimet[i]["vuosi"] = kisanimet[i]["alkuaika"].year
    except:
        pass

    #haetaan sisäänkirjautuvan joukkueen tiedot
    try:
        sql = '''SELECT sarja, id, joukkuenimi, salasana
        FROM joukkueet
        WHERE joukkuenimi = %s'''
        cur.execute(sql, (joukkue,))
        joukkueenTiedot = cur.fetchall()
    except:
        joukkueenTiedot = []

    #haetaan sisäänkirjautuvan joukkueen kilpailu
    try:
        sql = '''SELECT kilpailu
        FROM sarjat
        WHERE id = %s'''
        cur.execute(sql, (joukkueenTiedot[0]['sarja'],))
        kilpailu = cur.fetchall()
        kilpailu = kilpailu[0]['kilpailu']
    except:
        kilpailu = ""

    # sisäänkirjautuminen. asetetaan evästeet ja siirrytään listaus-sivulle, jos kirjautuminen onnistuu
    teksti = ""
    try:
        m = hashlib.sha512()
        avain = str(joukkueenTiedot[0]['id'])
        m.update(avain.encode("UTF-8"))
        m.update(salasana.encode("UTF-8"))

        if int(kilpailu) == int(valittuKisa) and m.hexdigest() == joukkueenTiedot[0]['salasana']:
            session['kirjautunut'] = "ok"
            session['kirjautunutJoukkue'] = joukkueenTiedot[0]['id']
            session['kirjautuneenNimi'] = joukkueenTiedot[0]['joukkuenimi']
            session['kirjautuneenKilpailu'] = kilpailu
            session['kirjautuneenSarja'] = joukkueenTiedot[0]['sarja']

            try:
                sql = '''SELECT kisanimi, alkuaika
                FROM kilpailut
                WHERE id = %s'''
                cur.execute(sql, (kilpailu,))
                tulos = cur.fetchall()
                session['kirjautuneenKilpailunNimi'] = tulos[0]['kisanimi']
                session['kirjautuneenKilpailunAlkuaika'] = str(tulos[0]['alkuaika'])
            except:
                return "Tietojen hakeminen epäonnistui"
            con.close()
            return redirect(url_for('listaus'))
    except:
        pass

    # jos päästään tänne asti, kirjautuminen epäonnistui
    if valittuKisa != "":
        teksti = "Kirjautuminen epäonnistui"

    con.close()

    try:
        return render_template('jinja.html', joukkueenTiedot=joukkueenTiedot, teksti=teksti,kisanimet=kisanimet, joukkue=joukkue,
        kilpailu=kilpailu,valittuKisa=valittuKisa)
    except:
        return render_template('jinja.html')

@app.route('/listaus', methods=['GET', 'POST'])
@auth
def listaus():

    try:
        pool=mysql.connector.pooling.MySQLConnectionPool(pool_name="tietokantayhteydet",
        pool_size=2, #PythonAnywheren ilmaisen tunnuksen maksimi on kolme
        **dbconfig
        )
        con = pool.get_connection()
    except mysql.connector.Error:
        return "Yhdistäminen tietokantaan epäonnistui"

    # haetaan kilpailun sarjat
    try:
        cur = con.cursor(buffered=True, dictionary=True)
        sql = '''SELECT id, sarjanimi
        FROM sarjat
        WHERE kilpailu = %s
        ORDER BY sarjanimi'''
        cur.execute(sql, (session['kirjautuneenKilpailu'],))
        kilpailunSarjat = cur.fetchall()
    except:
        return "Sarjojen haku epäonnistui"

    # haetaan kilpailun kaikkien sarjojen joukkueiden tiedot
    kaikkienSarjojenJoukkueet = []
    for i in range(len(kilpailunSarjat)):
        try:
            sql = '''SELECT joukkueet.joukkuenimi, joukkueet.jasenet, sarjat.sarjanimi
            FROM joukkueet, sarjat
            WHERE joukkueet.sarja = sarjat.id
            AND sarjat.kilpailu = %s
            AND sarjat.id = %s
            ORDER BY LOWER(joukkueet.joukkuenimi)'''
            cur.execute(sql, (session['kirjautuneenKilpailu'],kilpailunSarjat[i]['id']))
            sarjanJoukkueet = cur.fetchall() #haetaan kaikki kyselyn tulokset
            for i in sarjanJoukkueet:
                i['jasenet'] = json.loads(i['jasenet'])
                i['jasenet'].sort() 
            kaikkienSarjojenJoukkueet.append(sarjanJoukkueet)
        except:
            return "Tietojen haku epäonnistui"

    con.close()

    try:
        return render_template('listaus.html', kaikkienSarjojenJoukkueet=kaikkienSarjojenJoukkueet)
    except:
        return render_template('listaus.html')

@app.route('/tiedot', methods=['GET', 'POST'])
@auth
def tiedot():

    # valittu sarja radio button
    try:
        option = request.form.get('sarjanapit')
    except:
        option = []

    # haetaan lisättävät jäsenet kenntistä
    uudetJasenet = []
    ekaTyhja = ""
    try:
        paivitettyNimi = request.form.get('nimi', "")
        tuplanaOlevaNimi = ""

        for i in range(5):
            if request.form.get('jasen'+str(i+1), "") in uudetJasenet:
                tuplanaOlevaNimi = request.form.get('jasen'+str(i+1), "")
            if request.form.get('jasen'+str(i+1), "") != "":
                uudetJasenet.append(request.form.get('jasen'+str(i+1), ""))
            elif ekaTyhja == "":
                ekaTyhja = int(i+1)
    except:
        paivitettyNimi = ""
        paivitettyjasen1 = ""
        paivitettyjasen2 = ""
        paivitettyjasen3 = ""
        paivitettyjasen4 = ""
        paivitettyjasen5 = ""

    try:
        pool=mysql.connector.pooling.MySQLConnectionPool(pool_name="tietokantayhteydet",
        pool_size=2, #PythonAnywheren ilmaisen tunnuksen maksimi on kolme
        **dbconfig
        )
        con = pool.get_connection()
    except mysql.connector.Error:
        return "Yhdistäminen tietokantaan epäonnistui"

    # haetaan kilpailun kaikki joukkueet
    try:
        cur = con.cursor(buffered=True, dictionary=True)
        sql = '''SELECT joukkueet.joukkuenimi
        FROM joukkueet, sarjat
        WHERE joukkueet.sarja = sarjat.id
        AND sarjat.kilpailu = %s
        AND NOT joukkueet.id = %s'''
        cur.execute(sql, (session['kirjautuneenKilpailu'], session['kirjautunutJoukkue']))
        kilpailunJoukkueet = cur.fetchall() #haetaan kaikki kyselyn tulokset
    except:
        return "Epäonnistui"

    # päivitetään joukkueen tiedot, jos kaikki ehdot täyttyvät
    if len(uudetJasenet) > 1 and paivitettyNimi not in [d['joukkuenimi'] for d in kilpailunJoukkueet] and len(paivitettyNimi) > 0 and tuplanaOlevaNimi == "":
        try:
            sql = '''UPDATE joukkueet
            SET jasenet = %s, joukkuenimi = %s, sarja = %s
            WHERE id = %s'''
            cur.execute(sql, (json.dumps(uudetJasenet),paivitettyNimi,option,session['kirjautunutJoukkue']))

            session['kirjautuneenNimi'] = paivitettyNimi
            session['kirjautuneenSarja'] = option
        except:
            return "Epäonnistui"

    # haetaan kilpailun sarjat
    try:
        sql = '''SELECT sarjanimi, id
        FROM sarjat
        WHERE kilpailu = %s'''
        cur.execute(sql, (session['kirjautuneenKilpailu'],))
        sarjat = cur.fetchall()
        sarjanimet = []
        for i in sarjat:
            sarjanimet.append((i['id'], i['sarjanimi']))
    except:
        return "epäonnistui"

    # haetaan kirjautuneen joukkueen tiedot
    kirjautuneenJasenet = []
    try:
        sql = '''SELECT jasenet, joukkuenimi, sarja
        FROM joukkueet
        WHERE id = %s'''
        cur.execute(sql, (session['kirjautunutJoukkue'],))
        jasenet = cur.fetchall()

        for i in jasenet:
            i['jasenet'] = json.loads(i['jasenet'])

        for i in range(5):
            try:
                kirjautuneenJasenet.append(jasenet[0]['jasenet'][i])
            except:
                kirjautuneenJasenet.append("")

    except:
        return "epäonnistui"

    class Lomake(PolyglotForm): #PolyglotForm
        sarjanapit = RadioField('Label', choices=sarjanimet, default=session['kirjautuneenSarja'])
        nimi = StringField('Joukkueen nimi:', default=session['kirjautuneenNimi'])
        def validate_nimi(form, field):
            if len(paivitettyNimi) < 1:
                raise ValidationError("Täytä kenttä.")
            if paivitettyNimi in [d['joukkuenimi'] for d in kilpailunJoukkueet]:
                raise ValidationError("Joukkuenimi on jo valitussa kilpailussa.")
        jasen1 = StringField('Jäsen 1:', default=kirjautuneenJasenet[0])
        def validate_jasen1(form, field):
            if tuplanaOlevaNimi != "" and tuplanaOlevaNimi == request.form.get('jasen1'):
                raise ValidationError("Ei saa olla saman nimisiä jäseniä.")
            if ekaTyhja == 1 and len(uudetJasenet) < 2:
                raise ValidationError("Joukkueella on oltava vähintään kaksi jäsentä.")
        jasen2 = StringField('Jäsen 2:', default=kirjautuneenJasenet[1])
        def validate_jasen2(form, field):
            if tuplanaOlevaNimi != "" and tuplanaOlevaNimi == request.form.get('jasen2'):
                raise ValidationError("Ei saa olla saman nimisiä jäseniä.")
            if ekaTyhja == 2 and len(uudetJasenet) < 2:
                raise ValidationError("Joukkueella on oltava vähintään kaksi jäsentä.")
        jasen3 = StringField('Jäsen 3:', default=kirjautuneenJasenet[2])
        def validate_jasen3(form, field):
            if tuplanaOlevaNimi != "" and tuplanaOlevaNimi == request.form.get('jasen3'):
                raise ValidationError("Ei saa olla saman nimisiä jäseniä.")
        jasen4 = StringField('Jäsen 4:', default=kirjautuneenJasenet[3])
        def validate_jasen4(form, field):
            if tuplanaOlevaNimi != "" and tuplanaOlevaNimi == request.form.get('jasen4'):
                raise ValidationError("Ei saa olla saman nimisiä jäseniä.")
        jasen5 = StringField('Jäsen 5:', default=kirjautuneenJasenet[4])
        def validate_jasen5(form, field):
            if tuplanaOlevaNimi != "" and tuplanaOlevaNimi == request.form.get('jasen5'):
                raise ValidationError("Ei saa olla saman nimisiä jäseniä.")

    form=Lomake()

    if request.method == 'POST':
        form.validate()
    if request.method == "POST":
       form.validate()
    elif request.method == "GET" and request.args:
       form = Lomake(request.args)
       form.validate()
    else:
       form = Lomake()

    con.commit()
    con.close()

    return render_template('tiedot.html', form=form)