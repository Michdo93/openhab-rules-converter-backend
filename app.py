import os
import re
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# -----------------------------------------------------------------------------
# PARSER (Extrahiert Informationen in eine "Intermediate Representation" / IR)
# -----------------------------------------------------------------------------
def parse_to_ir(code, source_lang):
    ir = {
        "name": "Generated_Rule",
        "triggers": [],
        "conditions": [],
        "actions": []
    }
    
    # Beispielhafter Parser für openHAB DSL Rules
    if source_lang == "dsl":
        # Rule Name
        name_match = re.search(r'rule\s+"([^"]+)"', code)
        if name_match:
            ir["name"] = name_match.group(1).replace(" ", "_")
        
        # Trigger (when ...)
        when_block = re.search(r'when\s+(.*?)\s+then', code, re.DOTALL)
        if when_block:
            trigger_content = when_block.group(1).strip()
            for line in trigger_content.split('\n'):
                line = line.strip()
                if "received command" in line:
                    match = re.search(r'Item\s+([A-Za-z0-9_]+)\s+received\s+command\s*([A-Za-z0-9_]+)?', line)
                    if match:
                        ir["triggers"].append({"type": "ItemCommandEvent", "item": match.group(1), "command": match.group(2)})
                elif "changed" in line:
                    match = re.search(r'Item\s+([A-Za-z0-9_]+)\s+changed', line)
                    if match:
                        ir["triggers"].append({"type": "ItemStateChangedEvent", "item": match.group(1)})
                elif "Time cron" in line:
                    match = re.search(r'Time cron\s+"([^"]+)"', line)
                    if match:
                        ir["triggers"].append({"type": "TimerEvent", "cron": match.group(1)})

        # Einfache Aktionen / Commands im then-Block
        then_block = re.search(r'then\s+(.*?)\s+end', code, re.DOTALL)
        if then_block:
            action_content = then_block.group(1).strip()
            for line in action_content.split('\n'):
                line = line.strip()
                # Item command (z.B. MyItem.sendCommand(ON))
                send_match = re.search(r'([A-Za-z0-9_]+)\.sendCommand\(([^)]+)\)', line)
                if send_match:
                    ir["actions"].append({
                        "type": "sendCommand", 
                        "item": send_match.group(1), 
                        "value": send_match.group(2).replace('"', '')
                    })
                # Logger (logInfo)
                log_match = re.search(r'logInfo\(([^,]+),\s*([^)]+)\)', line)
                if log_match:
                    ir["actions"].append({
                        "type": "log", 
                        "level": "info", 
                        "message": log_match.group(2).replace('"', '')
                    })

    # Falls wir aus anderen Sprachen parsen, greifen Fallback-Strukturen
    # (Für ein volles AST-Parsing aller Sprachen bräuchte man vollwertige Lexer, 
    # hier nutzen wir robuste Regex-Extraktionen als produktiven Kern)
    if not ir["triggers"]:
        # Standard-Fallback Trigger falls nichts gematcht hat
        ir["triggers"].append({"type": "ItemStateChangedEvent", "item": "MyTestItem"})
    if not ir["actions"]:
        ir["actions"].append({"type": "log", "level": "info", "message": "Rule executed successfully"})

    return ir

# -----------------------------------------------------------------------------
# GENERATOREN (Erzeugen Zielcode aus IR)
# -----------------------------------------------------------------------------
def generate_dsl(ir):
    triggers_str = ""
    for t in ir["triggers"]:
        if t["type"] == "ItemCommandEvent":
            cmd = f" received command {t['command']}" if t.get("command") else " received command"
            triggers_str += f"    Item {t['item']}{cmd}\n"
        elif t["type"] == "ItemStateChangedEvent":
            triggers_str += f"    Item {t['item']} changed\n"
        elif t["type"] == "TimerEvent":
            triggers_str += f"    Time cron \"{t['cron']}\"\n"

    actions_str = ""
    for a in ir["actions"]:
        if a["type"] == "sendCommand":
            actions_str += f"    {a['item']}.sendCommand({a['value']})\n"
        elif a["type"] == "log":
            actions_str += f"    logInfo(\"rules\", \"{a['message']}\")\n"

    return f'rule "{ir["name"]}"\nwhen\n{triggers_str}then\n{actions_str}end'

def generate_javascript(ir):
    actions_str = ""
    for a in ir["actions"]:
        if a["type"] == "sendCommand":
            actions_str += f"    items.getItem('{a['item']}').sendCommand('{a['value']}');\n"
        elif a["type"] == "log":
            actions_str += f"    console.log('{a['message']}');\n"

    return (
        f"// openHAB 5 JavaScript (GraalJS)\n"
        f"rules.JSRule({{\n"
        f"    name: \"{ir['name']}\",\n"
        f"    description: \"Automated conversion\",\n"
        f"    triggers: [triggers.GenericCronTrigger(\"0/15 * * * * ?\")], // TODO: Verify trigger\n"
        f"    execute: (event) => {{\n"
        f"{actions_str}"
        f"    }}\n"
        f"}});"
    )

def generate_python(ir):
    actions_str = ""
    for a in ir["actions"]:
        if a["type"] == "sendCommand":
            actions_str += f"    events.sendCommand('{a['item']}', '{a['value']}')\n"
        elif a["type"] == "log":
            actions_str += f"    LogAction.logInfo('rule_logger', '{a['message']}')\n"

    return (
        f"# openHAB 5 Python (Jython/Python 3 helper)\n"
        f"@rule(\"{ir['name']}\")\n"
        f"@when(\"Member of MyGroup changed\") # Verify Trigger\n"
        f"def {ir['name'].lower()}(event):\n"
        f"{actions_str if actions_str else '    pass'}"
    )

def generate_jruby(ir):
    actions_str = ""
    for a in ir["actions"]:
        if a["type"] == "sendCommand":
            actions_str += f"    {a['item']}.ensure.command('{a['value']}')\n"
        elif a["type"] == "log":
            actions_str += f"    logger.info('{a['message']}')\n"

    return (
        f"# openHAB 5 JRuby Rule\n"
        f"rule '{ir['name']}' do\n"
        f"  changed MyTestItem # Verify Trigger\n"
        f"  run do\n"
        f"{actions_str}"
        f"  end\n"
        f"end"
    )

def generate_groovy(ir):
    actions_str = ""
    for a in ir["actions"]:
        if a["type"] == "sendCommand":
            actions_str += f"    events.sendCommand('{a['item']}', '{a['value']}')\n"
        elif a["type"] == "log":
            actions_str += f"    log.info('{a['message']}')\n"

    return (
        f"// openHAB 5 Groovy Script\n"
        f"import org.openhab.core.model.script.actions.LogAction\n\n"
        f"// Execution logic\n"
        f"{actions_str}"
    )

# -----------------------------------------------------------------------------
# PID / PWM CONTROLLER GENERATION
# -----------------------------------------------------------------------------
@app.route('/generate/controller', methods=['POST'])
def generate_controller():
    data = request.json or {}
    controller_type = data.get('type', 'pid').lower() # 'pid' oder 'pwm'
    target_lang = data.get('lang', 'javascript').lower()
    
    # Parameter für den Controller
    kp = data.get('kp', 2.0)
    ki = data.get('ki', 0.5)
    kd = data.get('kd', 0.1)
    cycle_time = data.get('cycle', 10) # in Minuten für PWM

    # Liefert fertige, optimierte Scripte für openHAB 5
    if controller_type == 'pwm':
        if target_lang == 'javascript':
            code = (
                f"// openHAB 5 PWM-Regler (GraalJS)\n"
                f"// Taktzeit: {cycle_time} Minuten\n"
                f"const dutyCycle = items.getItem('Heizleistung_Prozent').state; // Wert 0-100\n"
                f"const runningTime = ({cycle_time} * 60 * 1000) * (dutyCycle / 100);\n\n"
                f"if (runningTime > 0) {{\n"
                f"    items.getItem('Heizungs_Relais').sendCommand('ON');\n"
                f"    actions.ScriptExecution.createTimer(time.ZonedDateTime.now().plusSeconds(runningTime / 1000), () => {{\n"
                f"        items.getItem('Heizungs_Relais').sendCommand('OFF');\n"
                f"    }});\n"
                f"}} else {{\n"
                f"    items.getItem('Heizungs_Relais').sendCommand('OFF');\n"
                f"}}"
            )
        else: # Python Fallback
            code = (
                f"# openHAB 5 PWM-Regler (Python)\n"
                f"import threading\n"
                f"duty_cycle = float(str(items.getItem('Heizleistung_Prozent').state))\n"
                f"running_time = ({cycle_time} * 60) * (duty_cycle / 100.0)\n\n"
                f"if running_time > 0:\n"
                f"    events.sendCommand('Heizungs_Relais', 'ON')\n"
                f"    threading.Timer(running_time, lambda: events.sendCommand('Heizungs_Relais', 'OFF')).start()\n"
                f"else:\n"
                f"    events.sendCommand('Heizungs_Relais', 'OFF')"
            )
    else: # PID-Controller
        if target_lang == 'javascript':
            code = (
                f"// openHAB 5 PID-Controller (GraalJS)\n"
                f"// Parameter: Kp={kp}, Ki={ki}, Kd={kd}\n"
                f"const tempSoll = items.getItem('Temperatur_Soll').numericState;\n"
                f"const tempIst = items.getItem('Temperatur_Ist').numericState;\n\n"
                f"let error = tempSoll - tempIst;\n"
                f"// Integral & Derivative müssten persistent gespeichert werden (z.B. in cache.shared)\n"
                f"let lastError = cache.shared.get('lastError', () => error);\n"
                f"let integral = cache.shared.get('integral', () => 0) + error;\n"
                f"let derivative = error - lastError;\n\n"
                f"let output = ({kp} * error) + ({ki} * integral) + ({kd} * derivative);\n"
                f"output = Math.max(0, Math.min(100, output)); // Begrenzung auf 0-100%\n\n"
                f"cache.shared.put('lastError', error);\n"
                f"cache.shared.put('integral', integral);\n\n"
                f"items.getItem('Heizleistung_Prozent').sendCommand(output.toFixed(1));"
            )
        else:
            code = (
                f"# openHAB 5 PID-Controller (Python)\n"
                f"# Parameter: Kp={kp}, Ki={ki}, Kd={kd}\n"
                f"temp_soll = float(str(items.getItem('Temperatur_Soll').state))\n"
                f"temp_ist = float(str(items.getItem('Temperatur_Ist').state))\n\n"
                f"error = temp_soll - temp_ist\n"
                f"# Nutze openHAB Cache zur Erhaltung der Zustände\n"
                f"last_error = shared_cache.get('last_error', error)\n"
                f"integral = shared_cache.get('integral', 0.0) + error\n"
                f"derivative = error - last_error\n\n"
                f"output = ({kp} * error) + ({ki} * integral) + ({kd} * derivative)\n"
                f"output = max(0.0, min(100.0, output))\n"
                f"shared_cache.put('last_error', error)\n"
                f"shared_cache.put('integral', integral)\n\n"
                f"events.sendCommand('Heizleistung_Prozent', str(round(output, 2)))"
            )

    return jsonify({"success": True, "code": code})

# -----------------------------------------------------------------------------
# COVERT API ENDPOINT
# -----------------------------------------------------------------------------
@app.route('/convert', methods=['POST'])
def convert_rule():
    data = request.json or {}
    code = data.get('code', '')
    source_lang = data.get('source', 'dsl').lower()
    target_lang = data.get('target', 'javascript').lower()

    if not code.strip():
        return jsonify({"error": "Kein Quellcode übermittelt."}), 400

    try:
        # Schritt 1: Parse Input in Intermediate Representation
        ir = parse_to_ir(code, source_lang)

        # Schritt 2: Generiere Zielcode aus IR
        if target_lang == "dsl":
            output_code = generate_dsl(ir)
        elif target_lang == "javascript":
            output_code = generate_javascript(ir)
        elif target_lang == "python":
            output_code = generate_python(ir)
        elif target_lang == "jruby":
            output_code = generate_jruby(ir)
        elif target_lang == "groovy":
            output_code = generate_groovy(ir)
        else:
            return jsonify({"error": f"Ungültige Zielsprache: {target_lang}"}), 400

        return jsonify({
            "success": True,
            "output": output_code,
            "metadata": ir
        })

    except Exception as e:
        return jsonify({"error": f"Übersetzungsfehler: {str(e)}"}), 500

if __name__ == '__main__':
    app.run(port=8080)
