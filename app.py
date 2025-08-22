# app.py

from flask import Flask, render_template_string, request, jsonify, redirect, url_for, Response
import subprocess
import threading
import os
import json
from datetime import datetime, timezone
import boto3
import ipaddress
import time

app = Flask(__name__)

# ---------------- Config / Paths ----------------
TF_DIR = "terraform"
APPLY_LOG = os.path.join(TF_DIR, "terraform_apply.log")
DESTROY_LOG = os.path.join(TF_DIR, "terraform_destroy.log")
APPLY_STATUS = os.path.join(TF_DIR, "apply_status.json")
DESTROY_STATUS = os.path.join(TF_DIR, "destroy_status.json")
OUTPUTS_JSON = os.path.join(TF_DIR, "outputs.json")  # NEW

# Destroy protection
DESTROY_PASSWORD = os.environ.get("DESTROY_PASSWORD", "Destroy@426344")
DEFAULT_REGION = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))

# ---------------- Utilities ----------------
def ts() -> str:
    return datetime.now(timezone.utc).isoformat()

def write_status(path, **data):
    payload = {"updated_at": ts(), **data}
    try:
        with open(path, "w") as f:
            json.dump(payload, f, indent=2)
    except Exception as e:
        print(f"[WARN] could not write {path}: {e}")

def read_status(path):
    if not os.path.exists(path):
        return {"message": "no runs yet"}
    try:
        with open(path) as f:
            return json.load(f)
    except Exception as e:
        return {"error": f"failed to read status: {e}"}

def ensure_tf_init():
    if not os.path.exists(os.path.join(TF_DIR, ".terraform")):
        subprocess.run(
            ["terraform", "init", "-input=false", "-upgrade"],
            cwd=TF_DIR,
            check=False
        )

def terraform_capture_outputs():
    """
    Runs `terraform output -json`, simplifies the structure to a {k: value} dict,
    and writes it to OUTPUTS_JSON.
    """
    try:
        res = subprocess.run(
            ["terraform", "output", "-json"], cwd=TF_DIR, capture_output=True, text=True
        )
        if res.returncode != 0:
            # Write minimal info for debugging if outputs fail
            with open(OUTPUTS_JSON, "w") as f:
                json.dump({"error": "terraform output failed", "stderr": res.stderr}, f, indent=2)
            return

        raw = json.loads(res.stdout or "{}")
        simplified = {}
        for k, v in raw.items():
            # Terraform -json returns { value: X, type: ..., sensitive: ... }
            simplified[k] = v.get("value")
        with open(OUTPUTS_JSON, "w") as f:
            json.dump(simplified, f, indent=2)
    except Exception as e:
        with open(OUTPUTS_JSON, "w") as f:
            json.dump({"error": f"exception capturing outputs: {e}"}, f, indent=2)

def read_outputs():
    if not os.path.exists(OUTPUTS_JSON):
        return {"message": "no outputs yet"}
    try:
        with open(OUTPUTS_JSON) as f:
            return json.load(f)
    except Exception as e:
        return {"error": f"failed to read outputs: {e}"}

def run_terraform(command, logfile, statusfile, action_name):
    ensure_tf_init()
    write_status(statusfile, action=action_name, state="running", started_at=ts(), exit_code=None)

    exit_code = 0
    try:
        with open(logfile, "w") as f:
            proc = subprocess.Popen(
                command, cwd=TF_DIR, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
            )
            for line in proc.stdout:
                f.write(line)
                f.flush()
            proc.wait()
            exit_code = proc.returncode
    except Exception as e:
        with open(logfile, "a") as f:
            f.write(f"\n[ERROR] Exception while running Terraform: {e}\n")
        exit_code = -1

    # Capture/clear outputs based on the action result
    if action_name == "apply" and exit_code == 0:
        terraform_capture_outputs()
    elif action_name == "destroy" and exit_code == 0:
        # Clear outputs on successful destroy
        try:
            if os.path.exists(OUTPUTS_JSON):
                os.remove(OUTPUTS_JSON)
        except Exception:
            pass

    write_status(
        statusfile,
        action=action_name,
        state="success" if exit_code == 0 else "failed",
        ended_at=ts(),
        exit_code=exit_code,
    )

def get_state_list():
    try:
        res = subprocess.run(
            ["terraform", "state", "list"], cwd=TF_DIR, capture_output=True, text=True
        )
        if res.returncode != 0 or not res.stdout.strip():
            return "No resources currently managed by Terraform."
        return res.stdout
    except Exception as e:
        return f"Unable to read state: {e}"

def ec2_client(region):
    return boto3.client("ec2", region_name=region)

def is_public_subnet(subnet):
    return subnet.get("MapPublicIpOnLaunch", False)

def ip_in_subnet(ip_str: str, cidr: str) -> bool:
    try:
        return ipaddress.ip_address(ip_str) in ipaddress.ip_network(cidr, strict=False)
    except Exception:
        return False

def follow_log(filepath):
    # Wait for the file to be created by the subprocess
    while not os.path.exists(filepath):
        time.sleep(1)
    with open(filepath, 'r') as f:
        f.seek(0, os.SEEK_END)
        while True:
            line = f.readline()
            if not line:
                time.sleep(1)
                continue
            yield f'data: {line}\n\n'

# ---------------- HTML (no emojis) ----------------
BASE_STYLES = """
<style>
  :root {
    --bg: #f6f8fb; --surface: #ffffff; --ink: #0f172a; --muted: #64748b;
    --brand: #1f6feb; --border: #e2e8f0; --ok: #0f0; --err: #f55;
    --mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono","Courier New", monospace;
  }
  * { box-sizing: border-box; }
  body { margin: 0; font-family: Inter, system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif; color: var(--ink); background: var(--bg); }
  .container { max-width: 1100px; margin: 0 auto; padding: 28px 22px 40px; }

  .navbar { background: #0b1020; color: #fff; padding: 14px 0; margin-bottom: 18px; box-shadow: 0 2px 10px rgba(0,0,0,.12); }
  .navwrap { max-width: 1100px; margin: 0 auto; padding: 0 22px; display: flex; gap: 18px; align-items: center; justify-content: space-between; }
  .brand { font-weight: 700; letter-spacing: .2px; }
  .navlinks { display: flex; gap: 14px; flex-wrap: wrap; }
  .navlinks a { color: #e5e7eb; text-decoration: none; padding: 8px 12px; border-radius: 8px; }
  .navlinks a:hover { background: rgba(255,255,255,.08); color: #fff; }

  h1 { margin: 6px 0 20px; font-size: 28px; letter-spacing: .3px; }
  h2 { margin: 0 0 14px; font-size: 20px; color: var(--muted); font-weight: 600; }

  .card { background: var(--surface); border: 1px solid var(--border); border-radius: 14px; padding: 18px; box-shadow: 0 8px 24px rgba(2, 6, 23, .04); }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 18px; }

  form .form-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 18px 20px; margin-top: 8px; }
  label { font-size: 13px; color: var(--muted); margin-bottom: 8px; }
  input[type="text"], input[type="number"], select, input[type="search"], input[type="password"] {
    width: 100%; height: 40px; padding: 8px 12px; border: 1px solid var(--border); border-radius: 10px; background: #fff; font-size: 14px; outline: none; transition: border-color .15s ease, box-shadow .15s ease;
  }
  input:focus, select:focus { border-color: var(--brand); box-shadow: 0 0 0 4px rgba(31,111,235,.10); }
  small.hint { color: var(--muted); display: block; margin-top: 8px; }

  .actions { margin-top: 18px; display: flex; gap: 10px; flex-wrap: wrap; }
  button { padding: 10px 16px; font-size: 14px; border: 1px solid var(--border); border-radius: 10px; background: #fff; cursor: pointer; }
  button.primary { background: var(--brand); border-color: var(--brand); color: #fff; }
  button:hover { filter: brightness(.98); }

  pre { background:#0b1020; color: var(--ok); padding: 14px; border-radius: 12px; white-space: pre-wrap; font-family: var(--mono); font-size: 12px; border: 1px solid #141a33; }
  .pre-danger { color: var(--err); }

  iframe { width: 100%; height: 320px; border: 1px solid var(--border); border-radius: 12px; background: #0b1020; resize: vertical; overflow: auto; }
</style>
"""

NAVBAR = """
<div class="navbar">
  <div class="navwrap">
    <div class="brand">Terraform UI</div>
    <div class="navlinks">
      <a href="/apply">Provision</a>
      <a href="/status">Status</a>
      <a href="/.logs">Logs Editor</a>
    </div>
  </div>
</div>
"""

APPLY_FORM = (
    "<html><head>"
    + BASE_STYLES
    + """
  <script>
    async function fetchRegions() {
      const res = await fetch(`/list_regions`);
      const data = await res.json();
      const sel = document.getElementById('region');
      sel.innerHTML = '';
      data.regions.forEach(r => {
        const opt = document.createElement('option');
        opt.value = r;
        opt.text = r;
        sel.appendChild(opt);
      });
      const defaultRegion = "{{ default_region }}";
      if (defaultRegion && [...sel.options].some(o => o.value === defaultRegion)) {
        sel.value = defaultRegion;
      }
      fetchVpcs();
      fetchKeyPairs();
    }

    async function fetchVpcs() {
      const region = document.getElementById('region').value;
      const vpcSel = document.getElementById('vpc_id');
      const subnetSel = document.getElementById('subnet_id');

      vpcSel.innerHTML = '<option value="">-- Select VPC --</option>';
      subnetSel.innerHTML = '<option value="">-- Select Subnet --</option>';
      document.getElementById('vpcRange').innerText = '';
      document.getElementById('subnetRange').innerText = '';

      if (!region) return;

      const res = await fetch(`/list_vpcs?region=${region}`);
      const data = await res.json();
      data.vpcs.forEach(v => {
        const opt = document.createElement('option');
        opt.value = v.vpc_id;
        opt.text = v.vpc_id + " (" + v.cidr + ")" + (v.name ? " - " + v.name : "");
        vpcSel.appendChild(opt);
      });
    }

    async function fetchKeyPairs() {
      const region = document.getElementById('region').value;
      const keySel = document.getElementById('key_name');
      keySel.innerHTML = '';
      const noneOpt = document.createElement('option');
      noneOpt.value = "";
      noneOpt.text = "-- No key pair (disable SSH/RDP) --";
      keySel.appendChild(noneOpt);

      if (!region) return;

      const res = await fetch(`/list_keypairs?region=${region}`);
      const data = await res.json();
      data.keypairs.forEach(k => {
        const opt = document.createElement('option');
        opt.value = k.name;
        opt.text = k.name;
        keySel.appendChild(opt);
      });
    }

    async function onRegionChange() {
      await fetchVpcs();
      await fetchKeyPairs();
    }

    async function onVpcChange() {
      await showVpcRange();
      await fetchSubnetsForVpc();
    }

    async function fetchSubnetsForVpc() {
      const region = document.getElementById('region').value;
      const vpcId  = document.getElementById('vpc_id').value;
      const subnetSel = document.getElementById('subnet_id');

      subnetSel.innerHTML = '<option value="">-- Select Subnet --</option>';
      document.getElementById('subnetRange').innerText = '';

      if (!region || !vpcId) return;

      const res = await fetch(`/list_subnets?region=${region}&vpc_id=${vpcId}`);
      const data = await res.json();
      data.subnets.forEach(s => {
        const opt = document.createElement('option');
        opt.value = s.subnet_id;
        opt.text = s.subnet_id + " (" + s.cidr + ") - " + s.type;
        subnetSel.appendChild(opt);
      });
    }

    async function showVpcRange() {
      const region = document.getElementById('region').value;
      const vpcId = document.getElementById('vpc_id').value;
      if (!region || !vpcId) {
        document.getElementById('vpcRange').innerText = '';
        return;
      }
      const res = await fetch(`/get_vpc_range?region=${region}&vpc_id=${vpcId}`);
      const data = await res.json();
      document.getElementById('vpcRange').innerText = "VPC CIDR: " + data.cidr;
    }

    async function showSubnetRange() {
      const region = document.getElementById('region').value;
      const subnetId = document.getElementById('subnet_id').value;
      if (!region || !subnetId) {
        document.getElementById('subnetRange').innerText = '';
        return;
      }
      const res = await fetch(`/get_subnet_range?region=${region}&subnet_id=${subnetId}`);
      const data = await res.json();
      document.getElementById('subnetRange').innerText = "Subnet CIDR: " + data.cidr + " (" + data.type + ")";
    }

    window.addEventListener('DOMContentLoaded', fetchRegions);
  </script>
</head>
<body>
  """
    + NAVBAR
    + """
  <div class="container">
    <h1>Provision a New EC2 Instance</h1>
    <div class="card">
      <form method="POST" action="/apply" onsubmit="return confirm('Proceed with provisioning?');">
        <div class="form-grid">
          <div>
            <label>Region</label>
            <select id="region" name="region" onchange="onRegionChange()" required></select>
          </div>

          <div>
            <label>VPC</label>
            <select id="vpc_id" name="vpc_id" onchange="onVpcChange()" required>
              <option value="">-- Select VPC --</option>
            </select>
            <small id="vpcRange" class="hint"></small>
          </div>

          <div>
            <label>Subnet</label>
            <select id="subnet_id" name="subnet_id" onchange="showSubnetRange()" required>
              <option value="">-- Select Subnet --</option>
            </select>
            <small id="subnetRange" class="hint"></small>
            <small class="hint">Subnets labeled public/private are informational only.</small>
          </div>

          <div>
            <label>Operating System</label>
            <select name="os_type" required>
              <option value="windows2019">Windows Server 2019 (latest)</option>
              <option value="windows2022">Windows Server 2022 (latest)</option>
              <option value="linux">Amazon Linux 2 (latest)</option>
            </select>
          </div>

          <div>
            <label>Instance Type</label>
            <input type="text" name="instance_type" value="t3.micro" required />
          </div>

          <div>
            <label>Key Pair (optional)</label>
            <select id="key_name" name="key_name"></select>
            <small class="hint">Choose a key pair for SSH/RDP access, or select “No key pair”.</small>
          </div>

          <div>
            <label>Instance Name (optional)</label>
            <input type="text" name="instance_name" placeholder="e.g., app-server-01" />
            <small class="hint">If left blank, Terraform will use a default name.</small>
          </div>

          <div>
            <label>Private IP (static)</label>
            <input type="text" name="private_ip" placeholder="e.g., 10.0.1.25" required />
            <small class="hint">Must be inside the selected subnet CIDR and not in use.</small>
          </div>
        </div>

        <div class="actions">
          <button class="primary" type="submit">Provision</button>
          <button type="button" onclick="window.location.href='/status'">Go to Status</button>
          <button type="button" onclick="window.location.href='/.logs'">Go to Logs</button>
        </div>
      </form>
    </div>
  </div>
</body>
</html>
"""
)

STATUS_HTML = (
    "<html><head>"
    + BASE_STYLES
    + """
  <script>
    async function destroyPrompt() {
      const pwd = prompt("Enter destroy password:");
      if (pwd === null) return;
      const res = await fetch("/destroy", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password: pwd })
      });
      if (res.ok) {
        alert("Destroy triggered. Watch the status and logs below.");
      } else {
        const txt = await res.text();
        alert("Destroy rejected: " + txt);
      }
    }

    function fmtOutputs(o) {
      try {
        return JSON.stringify(o, null, 2);
      } catch {
        return String(o);
      }
    }

    async function refreshStatus() {
      try {
        const res = await fetch("/api/status");
        const data = await res.json();

        document.getElementById("state").textContent = data.state || "No state";
        document.getElementById("apply_status").textContent = JSON.stringify(data.apply, null, 2);
        document.getElementById("destroy_status").textContent = JSON.stringify(data.destroy, null, 2);
        document.getElementById("outputs").textContent = fmtOutputs(data.outputs || { message: "no outputs yet" });

        // Optional: show a handy line if instance_id present
        const meta = document.getElementById("instance_meta");
        if (data.outputs && data.outputs.instance_id) {
          const region = data.outputs.region || "{{ default_region }}";
          meta.textContent = `Instance: ${data.outputs.instance_id}  •  Region: ${region}`;
        } else {
          meta.textContent = "";
        }
      } catch (e) {
        console.error("Failed to refresh status:", e);
      }
    }

    window.addEventListener("DOMContentLoaded", () => {
      refreshStatus();
      setInterval(refreshStatus, 5000);
    });
  </script>
</head>
<body>
  """
    + NAVBAR
    + """
  <div class="container">
    <h1>Terraform UI · Status and Live Logs</h1>

    <div class="actions" style="margin-top:0; margin-bottom:12px;">
      <button onclick="window.location.href='/apply'">New Provision</button>
      <button onclick="window.location.href='/.logs'">Open Logs</button>
      <button onclick="destroyPrompt()">Destroy (Password Required)</button>
    </div>

    <div class="grid" style="margin-bottom:22px;">
      <div class="card">
        <h2>Terraform State</h2>
        <pre id="state">{{ state }}</pre>
      </div>

      <div class="card">
        <h2>Last Apply Status</h2>
        <pre id="apply_status">{{ apply_status }}</pre>
      </div>

      <div class="card">
        <h2>Last Destroy Status</h2>
        <pre id="destroy_status" class="pre-danger">{{ destroy_status }}</pre>
      </div>
    </div>

    <div class="grid" style="margin-bottom:22px;">
      <div class="card">
        <h2>Latest Outputs</h2>
        <div id="instance_meta" style="font-size:13px; color:#64748b; margin-bottom:8px;"></div>
        <pre id="outputs">{ "message": "no outputs yet" }</pre>
      </div>
    </div>

    <div class="grid">
      <div class="card">
        <h2>Live Apply Logs</h2>
        <iframe src="/apply_logs"></iframe>
      </div>
      <div class="card">
        <h2>Live Destroy Logs</h2>
        <iframe src="/destroy_logs"></iframe>
      </div>
    </div>
  </div>
</body>
</html>
"""
)

LOGS_EDITOR_HTML = (
    "<html><head>"
    + BASE_STYLES
    + """
</head>
<body>
  """
    + NAVBAR
    + """
  <div class="container">
    <h1>Logs Editor</h1>
    <div class="grid">
      <div class="card">
        <h2>Apply Log</h2>
        <form method="POST" action="/.logs">
          <input type="hidden" name="target" value="apply" />
          <textarea name="content" style="width:100%; height:300px; font-family: var(--mono);">{{ apply_log }}</textarea>
          <div class="actions">
            <button class="primary" type="submit">Save</button>
            <button type="submit" name="clear" value="1">Clear</button>
          </div>
        </form>
      </div>

      <div class="card">
        <h2>Destroy Log</h2>
        <form method="POST" action="/.logs">
          <input type="hidden" name="target" value="destroy" />
          <textarea name="content" style="width:100%; height:300px; font-family: var(--mono);">{{ destroy_log }}</textarea>
          <div class="actions">
            <button class="primary" type="submit">Save</button>
            <button type="submit" name="clear" value="1">Clear</button>
          </div>
        </form>
      </div>
    </div>
  </div>
</body>
</html>
"""
)

# ---------------- Routes ----------------
@app.route("/apply", methods=["GET", "POST"])
def apply_route():
    if request.method == "POST":
        os_type       = request.form["os_type"]
        instance_type = request.form["instance_type"]
        region        = request.form["region"]
        vpc_id        = request.form["vpc_id"]
        subnet_id     = request.form["subnet_id"]
        private_ip    = request.form["private_ip"]
        key_name      = request.form.get("key_name", "").strip()
        instance_name = request.form.get("instance_name", "").strip()

        # Validate subnet/IP before launching
        ec2 = ec2_client(region)
        try:
            subnet = ec2.describe_subnets(SubnetIds=[subnet_id])["Subnets"][0]
            subnet_cidr = subnet["CidrBlock"]
        except Exception as e:
            return f"<pre>Could not fetch subnet {subnet_id} in {region}: {e}</pre>", 400

        if not ip_in_subnet(private_ip, subnet_cidr):
            return f"<pre>Private IP {private_ip} is not inside subnet CIDR {subnet_cidr}.</pre>", 400

        # tfvars for Terraform
        os.makedirs(TF_DIR, exist_ok=True)
        with open(os.path.join(TF_DIR, "terraform.tfvars"), "w") as f:
            f.write(f'region        = "{region}"\n')
            f.write(f'os_type       = "{os_type}"\n')
            f.write(f'instance_type = "{instance_type}"\n')
            f.write(f'vpc_id        = "{vpc_id}"\n')
            f.write(f'subnet_id     = "{subnet_id}"\n')
            f.write(f'private_ip    = "{private_ip}"\n')
            f.write(f'key_name      = "{key_name}"\n')
            f.write(f'instance_name = "{instance_name}"\n')

        # Background apply
        threading.Thread(
            target=run_terraform,
            args=(["terraform", "apply", "-auto-approve"], APPLY_LOG, APPLY_STATUS, "apply"),
            daemon=True
        ).start()

        return redirect(url_for("status"))

    # GET -> form
    return render_template_string(APPLY_FORM, navbar=NAVBAR, default_region=DEFAULT_REGION)

@app.route("/", methods=["GET", "POST"])
def home():
    if request.method == "POST":
        return apply_route()
    return render_template_string(APPLY_FORM, navbar=NAVBAR, default_region=DEFAULT_REGION)

@app.route("/destroy", methods=["POST"])
def destroy():
    pwd = None
    if request.is_json:
        body = request.get_json(silent=True) or {}
        pwd = body.get("password")
    if not pwd:
        pwd = request.form.get("password")

    if pwd != DESTROY_PASSWORD:
        return "Unauthorized: invalid password.", 401

    threading.Thread(
        target=run_terraform,
        args=(["terraform", "destroy", "-auto-approve"], DESTROY_LOG, DESTROY_STATUS, "destroy"),
        daemon=True
    ).start()
    return "Destroy triggered.", 200

@app.route("/status")
def status():
    return render_template_string(
        STATUS_HTML,
        navbar=NAVBAR,
        title="Terraform UI · Status and Live Logs",
        state=get_state_list(),
        apply_status=json.dumps(read_status(APPLY_STATUS), indent=2),
        destroy_status=json.dumps(read_status(DESTROY_STATUS), indent=2),
        default_region=DEFAULT_REGION,
    )

# ---- Log viewers (Using SSE) ----
@app.route("/apply_logs")
def apply_logs():
    return """
    <html>
    <head>
        <title>Terraform UI · Apply Logs</title>
        <style>
            body { background: #0b1020; color: #0f0; font-family: ui-monospace, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace; padding: 20px; margin:0; }
            pre { white-space: pre-wrap; word-wrap: break-word; margin:0; }
        </style>
    </head>
    <body>
        <pre id="log-container"></pre>
        <script>
            var eventSource = new EventSource('/stream/apply_logs');
            eventSource.onmessage = function(e) {
                var logContainer = document.getElementById('log-container');
                logContainer.textContent += e.data + '\\n';
                window.scrollTo(0, document.body.scrollHeight);
            };
        </script>
    </body>
    </html>
    """

@app.route("/destroy_logs")
def destroy_logs():
    return """
    <html>
    <head>
        <title>Terraform UI · Destroy Logs</title>
        <style>
            body { background: #0b1020; color: #f55; font-family: ui-monospace, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace; padding: 20px; margin:0; }
            pre { white-space: pre-wrap; word-wrap: break-word; margin:0; }
        </style>
    </head>
    <body>
        <pre id="log-container"></pre>
        <script>
            var eventSource = new EventSource('/stream/destroy_logs');
            eventSource.onmessage = function(e) {
                var logContainer = document.getElementById('log-container');
                logContainer.textContent += e.data + '\\n';
                window.scrollTo(0, document.body.scrollHeight);
            };
        </script>
    </body>
    </html>
    """
    
# ---- SSE Streaming Routes ----
@app.route('/stream/apply_logs')
def stream_apply_logs():
    return Response(follow_log(APPLY_LOG), mimetype='text/event-stream')

@app.route('/stream/destroy_logs')
def stream_destroy_logs():
    return Response(follow_log(DESTROY_LOG), mimetype='text/event-stream')


# ---- JSON APIs ----
@app.route("/api/logs/<action>")
def api_logs(action):
    logfile = APPLY_LOG if action == "apply" else DESTROY_LOG
    if not os.path.exists(logfile):
        return jsonify({"logs": "No logs yet.", "action": action})
    with open(logfile, "r") as f:
        return jsonify({"logs": f.read(), "action": action})

@app.route("/api/status")
def api_status():
    return jsonify({
        "state": get_state_list(),
        "apply": read_status(APPLY_STATUS),
        "destroy": read_status(DESTROY_STATUS),
        "outputs": read_outputs(),  # NEW
    })

# ---- Logs Editor (simple) ----
@app.route("/.logs", methods=["GET", "POST"])
def edit_logs():
    if request.method == "POST":
        target  = request.form.get("target")
        content = request.form.get("content", "")
        clear   = request.form.get("clear")

        logfile = APPLY_LOG if target == "apply" else DESTROY_LOG
        try:
            if clear == "1":
                open(logfile, "w").close()
            else:
                with open(logfile, "w") as f:
                    f.write(content)
        except Exception as e:
            return f"<pre>Failed to write logs: {e}</pre>", 500

    apply_log = open(APPLY_LOG).read() if os.path.exists(APPLY_LOG) else ""
    destroy_log = open(DESTROY_LOG).read() if os.path.exists(DESTROY_LOG) else ""
    return render_template_string(
        LOGS_EDITOR_HTML,
        navbar=NAVBAR,
        apply_log=apply_log,
        destroy_log=destroy_log
    )

# ---- AWS Inventory ----
@app.route("/list_regions")
def list_regions():
    try:
        ec2 = boto3.client("ec2")
        regions = ec2.describe_regions(AllRegions=False)["Regions"]
        names = sorted([r["RegionName"] for r in regions])
        return jsonify({"regions": names})
    except Exception:
        return jsonify({"regions": [
            "us-east-1","us-east-2","us-west-1","us-west-2",
            "eu-west-1","eu-central-1",
            "ap-south-1","ap-southeast-1","ap-southeast-2"
        ]})

@app.route("/list_vpcs")
def list_vpcs():
    region = request.args.get("region", DEFAULT_REGION)
    ec2 = ec2_client(region)
    vpcs = ec2.describe_vpcs().get("Vpcs", [])
    out = []
    for v in vpcs:
        name = None
        for t in v.get("Tags", []):
            if t.get("Key") == "Name":
                name = t.get("Value")
                break
        out.append({"vpc_id": v["VpcId"], "cidr": v["CidrBlock"], "name": name})
    return jsonify({"vpcs": out})

@app.route("/list_subnets")
def list_subnets():
    region = request.args.get("region", DEFAULT_REGION)
    vpc_id = request.args.get("vpc_id")
    ec2 = ec2_client(region)
    kwargs = {}
    if vpc_id:
        kwargs["Filters"] = [{"Name": "vpc-id", "Values": [vpc_id]}]
    subnets = ec2.describe_subnets(**kwargs).get("Subnets", [])
    out = []
    for s in subnets:
        out.append({
            "subnet_id": s["SubnetId"],
            "cidr": s["CidrBlock"],
            "type": "public" if is_public_subnet(s) else "private"
        })
    return jsonify({"subnets": out})

@app.route("/list_keypairs")
def list_keypairs():
    region = request.args.get("region", DEFAULT_REGION)
    ec2 = ec2_client(region)
    kp = ec2.describe_key_pairs().get("KeyPairs", [])
    names = sorted([k.get("KeyName") for k in kp if k.get("KeyName")])
    return jsonify({"keypairs": [{"name": n} for n in names]})

@app.route("/get_vpc_range")
def get_vpc_range():
    region = request.args.get("region", DEFAULT_REGION)
    vpc_id = request.args.get("vpc_id")
    if not vpc_id:
        return jsonify({"error": "vpc_id required"}), 400
    ec2 = ec2_client(region)
    vpc = ec2.describe_vpcs(VpcIds=[vpc_id])["Vpcs"][0]
    return jsonify({"cidr": vpc["CidrBlock"]})

@app.route("/get_subnet_range")
def get_subnet_range():
    region = request.args.get("region", DEFAULT_REGION)
    subnet_id = request.args.get("subnet_id")
    if not subnet_id:
        return jsonify({"error": "subnet_id required"}), 400
    ec2 = ec2_client(region)
    subnet = ec2.describe_subnets(SubnetIds=[subnet_id])["Subnets"][0]
    return jsonify({
        "cidr": subnet["CidrBlock"],
        "type": "public" if is_public_subnet(subnet) else "private"
    })

# ---------------- Entry ----------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)

