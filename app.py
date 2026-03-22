from flask import Flask, render_template, Response
import subprocess
import time
import os

app = Flask(__name__)

def generate_output(script_name):
    """Generator to continuously yield stdout from a subprocess."""
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    process = subprocess.Popen(['python', '-u', script_name],
                               stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT,
                               text=True,
                               encoding='utf-8',
                               env=env)
    
    # Continuously yield lines from the subprocess as SSE
    for line in iter(process.stdout.readline, ''):
        if line:
            # Format as Server-Sent Event (SSE)
            cleaned = line.rstrip('\r\n')
            yield f"data: {cleaned}\n\n"
    
    process.stdout.close()
    process.wait()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/stream/vqc_filter')
def stream_vqc_filter():
    return Response(generate_output('vqc_filter.py'), mimetype='text/event-stream')

@app.route('/stream/vqc_noise_filter')
def stream_vqc_noise_filter():
    return Response(generate_output('vqc_noise_filter.py'), mimetype='text/event-stream')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
