from datetime import datetime
from icalendar import Calendar, Event
from flask import request, json
from app import rd, db, models, app
from .models import Module, Section, Lesson

@app.route('/')
def index():
    return app.send_static_file('index.html')

@app.route('/editor')
def group_editor():
    return app.send_static_file('editor.html')

@app.route('/locations')
def get_locations():
    return json.jsonify( rd.hgetall('locations') )

@app.route('/groups')
def get_groups():
    return json.jsonify({ g:tuple(rd.smembers('group:%s'%g)) for g in rd.smembers('groups') })

@app.route('/modules')
def get_modules():

    def module(m):
        sections = Section.query.filter_by(mod_code=m.code).all()
        return { 'title': m.title, 'sections': { s.class_no: s.details for s in sections } }

    return json.jsonify({ m.code: module(m) for m in Module.query.all() })

@app.route('/section/<int:cn>')
def get_section(cn):

    section = Section.query.get(cn)
    if not section: return json.jsonify({'status':'error'})

    def event(l):
        return {
            'title': l.title, 'description': str(l),
            'start': l.start.isoformat(), 'end': l.end.isoformat(),
        }

    schedule = [ event(lesson) for lesson in Lesson.query.filter_by(class_no=cn).all() ]

    return json.jsonify({'status':'ok', 'events':schedule, 'updated':section.updated})

@app.route('/calendar')
def get_timetable():

    def get_location( l ): return "%s (%s)" % ( locations.get(l,"TBD"), l )

    def get_event( lesson ):
        e = {
            'summary': lesson.title,
            'description': str(lesson),
            'location': get_location( lesson.location ),
            'dtstart': lesson.start, 'dtend': lesson.end,
        }

        event = Event()
        for k, v in e.items(): event.add(k,v)
        return event

    q = request.query_string.decode()
    if not q: return json.jsonify({'status':'error'})

    if ',' in q:
        calds = None
        codes = q.split(',')
    else:
        calds = q
        codes = rd.smembers('group:%s'%q)

    locations = rd.hgetall('locations')

    sections = []
    cal = Calendar()

    for cn in codes:
        try:
            cn = int(cn)
        except ValueError:
            continue

        section = Section.query.get(cn)
        if not section: continue

        schedule = Lesson.query.filter_by(class_no=cn).all()
        for lesson in schedule: cal.add_component( get_event( lesson ) )

        sections.append( str(section) )

    caldict = {
        'prodid': '-//SUTD Timetable Calendar//randName//EN',
        'version': '2.0',
        'calscale': 'GREGORIAN',
        'x-wr-timezone': 'Asia/Singapore',
        'x-wr-calname': 'Timetable',
        'x-wr-caldesc': 'Timetable for ' + calds if calds else ', '.join( sections ),
    }

    for k, v in caldict.items(): cal.add(k,v)

    return cal.to_ical(), 200, {'content-type': 'text/calendar'}

@app.route('/upload', methods=['POST'])
def load_data():
    
    module = request.get_json()
    if not Module.query.get(module['code']):
        db.session.add( Module(**{'code': module['code'], 'title': module['title']}) )

    sections = []
    for cn, section in module['sections'].items():
        cn = int(cn)
        sct = Section.query.get(cn)

        if not sct:
            sc = { 'class_no': cn, 'mod_code': module['code'], 'name': section['name'] }
            db.session.add( Section(**sc) )
            db.session.commit()
            print( "added %s" % sc )
        else:
            sct.last_updated = datetime.now()
            Lesson.query.filter_by(class_no=cn).delete()

        sections.append( section['name'] )

        sn = 0
        for i in section['schedule']:
            d = tuple( int(n) for n in reversed( i['d'].split('.') ) )
            dts = [ datetime(*(d+tuple(map(int,i[l].split('.'))))) for l in 'se' ]
            lesson = {
                'class_no': cn, 'sn': sn, 'dts': dts,
                'location': i['l'], 'component':i['c'],
            }
            db.session.add( Lesson(**lesson) )
            sn += 1

        db.session.commit()

    return json.jsonify({'status': 'ok','loaded': (module['code'], ', '.join(sections)) })
