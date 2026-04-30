from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from functools import wraps
import os, json, time, urllib.parse
from datetime import datetime, timedelta
import pg8000.native

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "isum_secret_cambiar")
APP_PASSWORD  = os.environ.get("ISUM_PASSWORD", "isum2024")
DATABASE_URL  = os.environ.get("DATABASE_URL", "")

MATERIAS = {
    "I":        ["Didactica Avanzada","Liderazgo y Administracion","Galatas, Juaninas","Psicologia Pastoral"],
    "II":       ["Etica Ministerial","Profetas Mayores: Isaias","Cristologia en Levitico","Hermeneutica Avanzada"],
    "III":      ["Teologia del Espiritu Santo","Misionologia: Comunicaciones Transculturales","Cristologia en Juan","Homiletica: Predicacion Expositiva"],
    "PROYECTO": ["PROYECTO","PROYECTO","PROYECTO","PROYECTO"],
}

DEFAULT_MASTER = {
    "paises":     {"Argentina":["Buenos Aires","Cordoba","Rosario"],
                   "Mexico":["Ciudad de Mexico","Guadalajara","Monterrey"],
                   "Colombia":["Bogota","Medellin","Cali"]},
    "enlaces":    {"Argentina":[],"Mexico":[],"Colombia":[]},
    "directores": [],
    "profesores": [],
    "honorarios": ["$500","$750","$1000","$1250","$1500","$2000"],
}

def parse_db_url(url):
    url = url.strip()
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    parsed = urllib.parse.urlparse(url)
    return {
        "user":     urllib.parse.unquote(parsed.username or ""),
        "password": urllib.parse.unquote(parsed.password or ""),
        "host":     parsed.hostname or "",
        "port":     parsed.port or 6543,
        "database": (parsed.path or "/postgres").lstrip("/"),
    }

def get_conn():
    p = parse_db_url(DATABASE_URL)
    return pg8000.native.Connection(
        user=p["user"], password=p["password"],
        host=p["host"], port=p["port"],
        database=p["database"], ssl_context=True)

def db_run(sql, **params):
    conn = get_conn()
    try:
        return conn.run(sql, **params) or []
    finally:
        conn.close()

def init_db():
    db_run("""CREATE TABLE IF NOT EXISTS seminarios (
        id SERIAL PRIMARY KEY, datos TEXT NOT NULL,
        creado TIMESTAMP DEFAULT NOW(), updated TIMESTAMP DEFAULT NOW())""")
    db_run("""CREATE TABLE IF NOT EXISTS master (
        id SERIAL PRIMARY KEY, datos TEXT NOT NULL)""")
    rows = db_run("SELECT COUNT(*) FROM master")
    if not rows or rows[0][0] == 0:
        db_run("INSERT INTO master (datos) VALUES (:d)", d=json.dumps(DEFAULT_MASTER))

for i in range(5):
    try: init_db(); break
    except Exception as e:
        if i < 4: time.sleep(3)
        else: print(f"ERROR init_db: {e}")

def get_master():
    try:
        rows = db_run("SELECT datos FROM master ORDER BY id LIMIT 1")
        m = json.loads(rows[0][0]) if rows else DEFAULT_MASTER
        # Asegurar que 'enlaces' existe aunque sea un master viejo
        if "enlaces" not in m:
            m["enlaces"] = {p: [] for p in m.get("paises", {}).keys()}
        return m
    except: return DEFAULT_MASTER

def save_master(data):
    rows = db_run("SELECT id FROM master ORDER BY id LIMIT 1")
    s = json.dumps(data, ensure_ascii=False)
    if rows: db_run("UPDATE master SET datos=:d WHERE id=:i", d=s, i=rows[0][0])
    else:    db_run("INSERT INTO master (datos) VALUES (:d)", d=s)

def get_seminarios():
    try:
        rows = db_run("SELECT id, datos FROM seminarios ORDER BY id")
        result = []
        for r in rows:
            d = json.loads(r[1]); d["_db_id"] = r[0]; result.append(d)
        return result
    except: return []

def get_seminario_by_dbid(db_id):
    rows = db_run("SELECT id, datos FROM seminarios WHERE id=:i", i=db_id)
    if rows:
        d = json.loads(rows[0][1]); d["_db_id"] = rows[0][0]; return d
    return None

def save_seminario(data, db_id=None):
    clean = {k: v for k, v in data.items() if k != "_db_id"}
    s = json.dumps(clean, ensure_ascii=False)
    if db_id: db_run("UPDATE seminarios SET datos=:d, updated=NOW() WHERE id=:i", d=s, i=db_id)
    else:     db_run("INSERT INTO seminarios (datos) VALUES (:d)", d=s)

def delete_seminario(db_id):
    db_run("DELETE FROM seminarios WHERE id=:i", i=db_id)

def parse_date(s):
    if not s: return None
    s = s.strip()
    for fmt in ("%d-%m-%Y","%d/%m/%Y","%d-%m-%y","%d/%m/%y","%-d-%-m-%Y","%-d-%-m-%y"):
        try:
            d = datetime.strptime(s, fmt)
            if d.year < 100: d = d.replace(year=d.year+2000)
            return d
        except: pass
    try:
        sep = "-" if "-" in s else "/"
        parts = s.split(sep)
        if len(parts)==3:
            day,month,year = int(parts[0]),int(parts[1]),int(parts[2])
            if year < 100: year += 2000
            return datetime(year,month,day)
    except: pass
    return None

def fmt_date(d): return d.strftime("%d-%m-%Y")

def detectar_conflictos_profesor(seminario_actual, todos):
    fi_a = parse_date(seminario_actual.get("fecha_inicio",""))
    id_a = seminario_actual.get("_db_id")
    if not fi_a: return {}
    campos_prof = [
        ("q0_m0_prof0","Materia 1"),("q0_m1_prof0","Materia 2"),
        ("q1_m0_prof0","Materia 3"),("q1_m1_prof0","Materia 4"),
    ]
    conflictos = {}
    for campo, label in campos_prof:
        prof = seminario_actual.get(campo,"").strip()
        if not prof: continue
        for s in todos:
            if s.get("_db_id") == id_a: continue
            fi_b = parse_date(s.get("fecha_inicio",""))
            if not fi_b: continue
            diff = abs((fi_a-fi_b).days)
            if diff <= 15:
                for c2,_ in campos_prof:
                    if s.get(c2,"").strip() == prof:
                        nombre_sem = f"{s.get('pais','?')} – {s.get('sede','?')} – Sem. {s.get('num_sem','?')} ({s.get('anio','')})"
                        if campo not in conflictos: conflictos[campo] = []
                        conflictos[campo].append({"profesor":prof,"seminario":nombre_sem,"label":label,"diff_dias":diff})
                        break
    return conflictos

def detectar_coincidencias(seminario_actual, todos):
    fi_a = parse_date(seminario_actual.get("fecha_inicio",""))
    fc_a = parse_date(seminario_actual.get("fecha_clausura",""))
    id_a = seminario_actual.get("_db_id")
    if not fi_a or not fc_a: return []
    coincidencias = []
    for s in todos:
        if s.get("_db_id") == id_a: continue
        fi_b = parse_date(s.get("fecha_inicio",""))
        fc_b = parse_date(s.get("fecha_clausura",""))
        if not fi_b or not fc_b: continue
        nombre_b = f"{s.get('pais','?')} – {s.get('sede','?')} – Sem. {s.get('num_sem','?')} ({s.get('anio','')})"
        if fi_a==fi_b and fc_a==fc_b:
            coincidencias.append({"tipo":"simultaneo","nombre":nombre_b})
        elif fi_a<=fc_b and fc_a>=fi_b and not (fi_a==fi_b and fc_a==fc_b):
            coincidencias.append({"tipo":"solapado","nombre":nombre_b})
    return coincidencias

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"): return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

@app.route("/login", methods=["GET","POST"])
def login():
    error = None
    if request.method == "POST":
        if request.form.get("password","").strip() == APP_PASSWORD:
            session["logged_in"] = True; return redirect(url_for("index"))
        error = "Contrasena incorrecta"
    return render_template("login.html", error=error)

@app.route("/logout")
def logout():
    session.clear(); return redirect(url_for("login"))

@app.route("/")
@login_required
def index():
    seminarios = get_seminarios()
    orden = request.args.get("orden","id")
    if orden == "fecha":
        seminarios.sort(key=lambda s: parse_date(s.get("fecha_inicio","")) or datetime(9999,1,1))
    elif orden == "fecha_desc":
        seminarios.sort(key=lambda s: parse_date(s.get("fecha_inicio","")) or datetime(1900,1,1), reverse=True)
    return render_template("index.html", seminarios=seminarios, orden=orden)

@app.route("/seminario/nuevo")
@login_required
def nuevo_seminario():
    return render_template("formulario.html", seminario={}, master=get_master(),
                           materias=MATERIAS, modo="nuevo", db_id=None,
                           coincidencias=[], conflictos_profesor={})

@app.route("/seminario/<int:db_id>/editar")
@login_required
def editar_seminario(db_id):
    s = get_seminario_by_dbid(db_id)
    if not s: return redirect(url_for("index"))
    todos = get_seminarios()
    return render_template("formulario.html", seminario=s, master=get_master(),
                           materias=MATERIAS, modo="editar", db_id=db_id,
                           coincidencias=detectar_coincidencias(s,todos),
                           conflictos_profesor=detectar_conflictos_profesor(s,todos))

@app.route("/seminario/guardar", methods=["POST"])
@login_required
def guardar_seminario():
    db_id = request.form.get("db_id")
    data  = {k: v for k, v in request.form.items() if k != "db_id"}
    fi   = parse_date(data.get("fecha_inicio",""))
    fi2q = parse_date(data.get("fecha_inicio_2q",""))
    if fi and not fi2q:
        fi2q = fi+timedelta(days=14); data["fecha_inicio_2q"] = fmt_date(fi2q)
    if fi2q: data["fecha_clausura"] = fmt_date(fi2q+timedelta(days=11))
    save_seminario(data, db_id=int(db_id) if db_id else None)
    flash("Seminario guardado correctamente.", "ok")
    return redirect(url_for("index"))

@app.route("/seminario/<int:db_id>/eliminar", methods=["POST"])
@login_required
def eliminar_seminario(db_id):
    delete_seminario(db_id)
    flash("Seminario eliminado.", "ok")
    return redirect(url_for("index"))

@app.route("/seminarios/eliminar-varios", methods=["POST"])
@login_required
def eliminar_varios_seminarios():
    ids = request.form.getlist("ids")
    for id_ in ids:
        try: delete_seminario(int(id_))
        except: pass
    flash(f"{len(ids)} seminario(s) eliminado(s).", "ok")
    return redirect(url_for("index"))

@app.route("/admin")
@login_required
def admin():
    return render_template("admin.html", master=get_master())

@app.route("/admin/guardar", methods=["POST"])
@login_required
def admin_guardar():
    try:
        master  = get_master()
        seccion = request.form.get("seccion","")
        accion  = request.form.get("accion","")
        valor   = request.form.get("valor","").strip()

        if seccion in ("directores","profesores","honorarios"):
            if accion=="agregar" and valor and valor not in master[seccion]:
                master[seccion].append(valor)
            elif accion=="eliminar" and valor in master[seccion]:
                master[seccion].remove(valor)
            elif accion=="importar":
                lineas=[l.strip() for l in valor.splitlines() if l.strip()]
                nuevos=[i for i in lineas if i not in master[seccion]]
                master[seccion].extend(nuevos)
                flash(f"{len(nuevos)} registros importados.","ok")
            elif accion=="ordenar":
                master[seccion]=sorted(master[seccion],key=lambda x:x.lower())
                flash("Lista ordenada alfabeticamente.","ok")
            elif accion=="borrar_todos":
                master[seccion]=[]; flash("Lista vaciada.","ok")
            elif accion=="eliminar_seleccionados":
                sel=request.form.getlist("seleccionados")
                master[seccion]=[x for x in master[seccion] if x not in sel]
                flash(f"{len(sel)} elemento(s) eliminado(s).","ok")

        elif seccion=="paises":
            pais=request.form.get("pais","").strip()
            if "enlaces" not in master:
                master["enlaces"] = {}
            if accion=="agregar_pais" and valor and valor not in master["paises"]:
                master["paises"][valor]=[]; master["enlaces"][valor]=[]
            elif accion=="eliminar_pais" and valor in master["paises"]:
                del master["paises"][valor]
                master["enlaces"].pop(valor, None)
            elif accion=="agregar_sede" and pais in master["paises"]:
                if valor and valor not in master["paises"][pais]:
                    master["paises"][pais].append(valor)
            elif accion=="eliminar_sede" and pais in master["paises"]:
                if valor in master["paises"][pais]:
                    master["paises"][pais].remove(valor)
            elif accion=="importar_sedes" and pais in master["paises"]:
                lineas=[l.strip() for l in valor.splitlines() if l.strip()]
                nuevos=[i for i in lineas if i not in master["paises"][pais]]
                master["paises"][pais].extend(nuevos)
                flash(f"{len(nuevos)} sedes importadas.","ok")
            elif accion=="ordenar_sedes" and pais in master["paises"]:
                master["paises"][pais]=sorted(master["paises"][pais],key=lambda x:x.lower())
                flash("Sedes ordenadas.","ok")
            elif accion=="eliminar_sedes_seleccionadas" and pais in master["paises"]:
                sel=request.form.getlist("seleccionados")
                master["paises"][pais]=[x for x in master["paises"][pais] if x not in sel]
                flash(f"{len(sel)} sede(s) eliminada(s).","ok")
            # ── Personas de enlace ──────────────────────────────────────────
            elif accion=="agregar_enlace" and pais:
                if pais not in master["enlaces"]: master["enlaces"][pais]=[]
                if valor and valor not in master["enlaces"][pais]:
                    master["enlaces"][pais].append(valor)
            elif accion=="eliminar_enlace" and pais:
                if pais in master["enlaces"] and valor in master["enlaces"][pais]:
                    master["enlaces"][pais].remove(valor)
            elif accion=="importar_enlaces" and pais:
                if pais not in master["enlaces"]: master["enlaces"][pais]=[]
                lineas=[l.strip() for l in valor.splitlines() if l.strip()]
                nuevos=[i for i in lineas if i not in master["enlaces"][pais]]
                master["enlaces"][pais].extend(nuevos)
                flash(f"{len(nuevos)} personas de enlace importadas.","ok")
            elif accion=="ordenar_enlaces" and pais:
                if pais in master["enlaces"]:
                    master["enlaces"][pais]=sorted(master["enlaces"][pais],key=lambda x:x.lower())
                    flash("Personas de enlace ordenadas.","ok")

        save_master(master)
        if "_" not in accion:
            flash("Datos guardados correctamente.","ok")
    except Exception as e:
        flash(f"Error al guardar: {str(e)}","error")
    return redirect(url_for("admin"))

@app.route("/reporte")
@login_required
def reporte():
    seminarios = get_seminarios()
    master     = get_master()
    f_pais     = request.args.get("pais","").strip()
    f_sede     = request.args.get("sede","").strip()
    f_director = request.args.get("director","").strip().lower()
    f_profesor = request.args.get("profesor","").strip().lower()
    f_fecha_desde = request.args.get("fecha_desde","").strip()
    f_fecha_hasta = request.args.get("fecha_hasta","").strip()
    orden      = request.args.get("orden","fecha")
    fd = parse_date(f_fecha_desde); fh = parse_date(f_fecha_hasta)

    def match(s):
        if f_pais and s.get("pais","")!=f_pais: return False
        if f_sede and s.get("sede","")!=f_sede: return False
        if f_director:
            if f_director not in s.get("director1","").lower() and f_director not in s.get("director2","").lower(): return False
        if f_profesor:
            encontrado=False
            for qi in range(2):
                for mi in range(2):
                    for opc in range(3):
                        if f_profesor in s.get(f"q{qi}_m{mi}_prof{opc}","").lower():
                            encontrado=True; break
            if not encontrado: return False
        fi=parse_date(s.get("fecha_inicio",""))
        if fd and fi and fi<fd: return False
        if fh and fi and fi>fh: return False
        return True

    resultados=[s for s in seminarios if match(s)]

    def sort_key(s):
        if orden=="pais": return (s.get("pais",""),s.get("sede",""))
        elif orden=="sede": return (s.get("sede",""),s.get("pais",""))
        else:
            fi=parse_date(s.get("fecha_inicio",""))
            return fi if fi else datetime(9999,1,1)
    resultados.sort(key=sort_key)

    sedes_disponibles=master["paises"].get(f_pais,[]) if f_pais else []
    return render_template("reporte.html",
                           resultados=resultados, materias=MATERIAS,
                           paises=list(master["paises"].keys()),
                           sedes_disponibles=sedes_disponibles,
                           directores=master["directores"],
                           profesores=master["profesores"],
                           f_pais=f_pais, f_sede=f_sede,
                           f_director=f_director, f_profesor=f_profesor,
                           f_fecha_desde=f_fecha_desde, f_fecha_hasta=f_fecha_hasta,
                           orden=orden, total=len(seminarios))

@app.route("/preview")
@login_required
def preview():
    seminarios=get_seminarios()
    sel_id=request.args.get("id",type=int)
    sel=None; coincidencias=[]; conflictos_profesor={}
    if sel_id:
        sel=next((s for s in seminarios if s.get("_db_id")==sel_id),None)
        if sel:
            coincidencias=detectar_coincidencias(sel,seminarios)
            conflictos_profesor=detectar_conflictos_profesor(sel,seminarios)
    return render_template("preview.html",
                           seminarios=seminarios, sel=sel, sel_id=sel_id,
                           materias=MATERIAS, coincidencias=coincidencias,
                           conflictos_profesor=conflictos_profesor)

@app.route("/debug/seminario/<int:db_id>")
@login_required
def debug_seminario(db_id):
    s=get_seminario_by_dbid(db_id); todos=get_seminarios()
    conflictos=detectar_conflictos_profesor(s,todos)
    claves_prof={k:v for k,v in s.items() if 'prof' in k}
    return jsonify({"claves_prof_en_seminario":claves_prof,
                    "conflictos_encontrados":conflictos,
                    "fecha_inicio":s.get("fecha_inicio",""),
                    "total_seminarios":len(todos)})

@app.route("/api/sedes")
@login_required
def api_sedes():
    pais=request.args.get("pais","")
    return jsonify(get_master()["paises"].get(pais,[]))

@app.route("/api/enlaces")
@login_required
def api_enlaces():
    pais=request.args.get("pais","")
    master=get_master()
    return jsonify(master.get("enlaces",{}).get(pais,[]))

if __name__=="__main__":
    app.run(host="0.0.0.0",port=int(os.environ.get("PORT",5000)),debug=False)
