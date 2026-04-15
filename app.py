from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from functools import wraps
import os, json, time
from datetime import datetime, timedelta
import psycopg2
from psycopg2.extras import RealDictCursor

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "isum_secret_cambiar")
APP_PASSWORD   = os.environ.get("ISUM_PASSWORD", "isum2024")
DATABASE_URL   = os.environ.get("DATABASE_URL", "")

MATERIAS = {
    "I":        ["Didactica Avanzada",          "Liderazgo y Administracion",                   "Galatas, Juaninas",         "Psicologia Pastoral"],
    "II":       ["Etica Ministerial",            "Profetas Mayores: Isaias",                     "Cristologia en Levitico",   "Hermeneutica Avanzada"],
    "III":      ["Teologia del Espiritu Santo",  "Misionologia: Comunicaciones Transculturales", "Cristologia en Juan",       "Homiletica: Predicacion Expositiva"],
    "PROYECTO": ["PROYECTO",                     "PROYECTO",                                     "PROYECTO",                  "PROYECTO"],
}

DEFAULT_MASTER = {
    "paises":     {"Argentina": ["Buenos Aires","Cordoba","Rosario"],
                   "Mexico":    ["Ciudad de Mexico","Guadalajara","Monterrey"],
                   "Colombia":  ["Bogota","Medellin","Cali"]},
    "directores": ["Director 1","Director 2","Director 3"],
    "profesores": ["Profesor A","Profesor B","Profesor C"],
    "honorarios": ["$500","$750","$1000","$1250","$1500","$2000"],
}

def get_conn():
    url = DATABASE_URL
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return psycopg2.connect(url, cursor_factory=RealDictCursor)

def init_db():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS seminarios (
                    id      SERIAL PRIMARY KEY,
                    datos   JSONB NOT NULL,
                    creado  TIMESTAMP DEFAULT NOW(),
                    updated TIMESTAMP DEFAULT NOW()
                );
                CREATE TABLE IF NOT EXISTS master (
                    id    SERIAL PRIMARY KEY,
                    datos JSONB NOT NULL
                );
            """)
            cur.execute("SELECT COUNT(*) as n FROM master")
            if cur.fetchone()["n"] == 0:
                cur.execute("INSERT INTO master (datos) VALUES (%s)",
                            [json.dumps(DEFAULT_MASTER)])
        conn.commit()

for intento in range(5):
    try:
        init_db(); break
    except Exception as e:
        if intento < 4: time.sleep(2)
        else: print(f"ERROR init_db: {e}")

def get_master():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT datos FROM master ORDER BY id LIMIT 1")
            row = cur.fetchone()
            return row["datos"] if row else DEFAULT_MASTER

def save_master(data):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM master ORDER BY id LIMIT 1")
            row = cur.fetchone()
            if row:
                cur.execute("UPDATE master SET datos=%s WHERE id=%s",
                            [json.dumps(data), row["id"]])
            else:
                cur.execute("INSERT INTO master (datos) VALUES (%s)", [json.dumps(data)])
        conn.commit()

def get_seminarios():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, datos FROM seminarios ORDER BY id")
            rows = cur.fetchall()
            result = []
            for r in rows:
                d = dict(r["datos"])
                d["_db_id"] = r["id"]
                result.append(d)
            return result

def get_seminario_by_dbid(db_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, datos FROM seminarios WHERE id=%s", [db_id])
            row = cur.fetchone()
            if row:
                d = dict(row["datos"])
                d["_db_id"] = row["id"]
                return d
    return None

def save_seminario(data, db_id=None):
    data_clean = {k: v for k, v in data.items() if k != "_db_id"}
    with get_conn() as conn:
        with conn.cursor() as cur:
            if db_id:
                cur.execute("UPDATE seminarios SET datos=%s, updated=NOW() WHERE id=%s",
                            [json.dumps(data_clean), db_id])
            else:
                cur.execute("INSERT INTO seminarios (datos) VALUES (%s)",
                            [json.dumps(data_clean)])
        conn.commit()

def delete_seminario(db_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM seminarios WHERE id=%s", [db_id])
        conn.commit()

def parse_date(s):
    for fmt in ("%d-%m-%Y","%d/%m/%Y","%d-%m-%y","%d/%m/%y"):
        try: return datetime.strptime(s.strip(), fmt)
        except: pass
    return None

def fmt_date(d): return d.strftime("%d-%m-%Y")

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

@app.route("/login", methods=["GET","POST"])
def login():
    error = None
    if request.method == "POST":
        if request.form.get("password") == APP_PASSWORD:
            session["logged_in"] = True
            return redirect(url_for("index"))
        error = "Contrasena incorrecta"
    return render_template("login.html", error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/")
@login_required
def index():
    seminarios = get_seminarios()
    return render_template("index.html", seminarios=seminarios)

@app.route("/seminario/nuevo")
@login_required
def nuevo_seminario():
    master = get_master()
    return render_template("formulario.html", seminario={}, master=master,
                           materias=MATERIAS, modo="nuevo", db_id=None)

@app.route("/seminario/<int:db_id>/editar")
@login_required
def editar_seminario(db_id):
    s = get_seminario_by_dbid(db_id)
    if not s: return redirect(url_for("index"))
    master = get_master()
    return render_template("formulario.html", seminario=s, master=master,
                           materias=MATERIAS, modo="editar", db_id=db_id)

@app.route("/seminario/guardar", methods=["POST"])
@login_required
def guardar_seminario():
    db_id = request.form.get("db_id")
    data  = {k: v for k, v in request.form.items() if k != "db_id"}
    fi   = parse_date(data.get("fecha_inicio",""))
    fi2q = parse_date(data.get("fecha_inicio_2q",""))
    if fi and not fi2q:
        fi2q = fi + timedelta(days=14)
        data["fecha_inicio_2q"] = fmt_date(fi2q)
    if fi2q:
        data["fecha_clausura"] = fmt_date(fi2q + timedelta(days=11))
    save_seminario(data, db_id=int(db_id) if db_id else None)
    flash("Seminario guardado correctamente.", "ok")
    return redirect(url_for("index"))

@app.route("/seminario/<int:db_id>/eliminar", methods=["POST"])
@login_required
def eliminar_seminario(db_id):
    delete_seminario(db_id)
    flash("Seminario eliminado.", "ok")
    return redirect(url_for("index"))

@app.route("/admin")
@login_required
def admin():
    master = get_master()
    return render_template("admin.html", master=master)

@app.route("/admin/guardar", methods=["POST"])
@login_required
def admin_guardar():
    master  = get_master()
    seccion = request.form.get("seccion")
    accion  = request.form.get("accion")
    valor   = request.form.get("valor","").strip()

    if seccion in ("directores","profesores","honorarios"):
        if accion == "agregar" and valor and valor not in master[seccion]:
            master[seccion].append(valor)
        elif accion == "eliminar" and valor in master[seccion]:
            master[seccion].remove(valor)
        elif accion == "importar":
            lineas = [l.strip() for l in valor.splitlines() if l.strip()]
            nuevos = [i for i in lineas if i not in master[seccion]]
            master[seccion].extend(nuevos)
            flash(f"{len(nuevos)} registros importados y grabados.", "ok")

    elif seccion == "paises":
        pais = request.form.get("pais","").strip()
        if accion == "agregar_pais" and valor and valor not in master["paises"]:
            master["paises"][valor] = []
        elif accion == "eliminar_pais" and valor in master["paises"]:
            del master["paises"][valor]
        elif accion == "agregar_sede" and pais in master["paises"]:
            if valor and valor not in master["paises"][pais]:
                master["paises"][pais].append(valor)
        elif accion == "eliminar_sede" and pais in master["paises"]:
            if valor in master["paises"][pais]:
                master["paises"][pais].remove(valor)
        elif accion == "importar_sedes" and pais in master["paises"]:
            lineas = [l.strip() for l in valor.splitlines() if l.strip()]
            nuevos = [i for i in lineas if i not in master["paises"][pais]]
            master["paises"][pais].extend(nuevos)
            flash(f"{len(nuevos)} sedes importadas y grabadas.", "ok")

    save_master(master)
    flash("Datos guardados correctamente.", "ok")
    return redirect(url_for("admin"))

@app.route("/api/sedes")
@login_required
def api_sedes():
    pais   = request.args.get("pais","")
    master = get_master()
    return jsonify(master["paises"].get(pais, []))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
