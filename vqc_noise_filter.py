import numpy as np
import time
import sounddevice as sd
from qiskit import QuantumCircuit
from qiskit.circuit import Parameter
from qiskit_aer import AerSimulator

# 🔹 Quantum simulator
simulator = AerSimulator()
print("⚙️ Using CPU Quantum Simulator\n")

theta = Parameter('θ')

# 🔹 Adaptive range
min_val = float('inf')
max_val = float('-inf')

# 🔹 Smoothing memory
prev_signal = 0.0

# 🔹 Hysteresis state
current_state = "✅ Clean Signal"

# 🔹 Quantum Circuit
def create_vqc():
    qc = QuantumCircuit(2)

    qc.ry(theta, 0)
    qc.ry(theta, 1)
    qc.cx(0, 1)
    qc.cz(1, 0)
    qc.rx(theta, 0)
    qc.rz(theta, 1)

    qc.measure_all()
    return qc

# 🔹 Adaptive normalization + smoothing
def normalize(x):
    global min_val, max_val, prev_signal

    min_val = min(min_val, x)
    max_val = max(max_val, x)

    if max_val - min_val < 1e-6:
        return 0.0

    norm = (x - min_val) / (max_val - min_val)

    # 🔥 smooth signal (realistic)
    smoothed = 0.7 * prev_signal + 0.3 * norm
    prev_signal = smoothed

    return smoothed

# 🔹 Mic input
def get_live_signal():
    duration = 0.5
    sample_rate = 44100

    audio = sd.rec(int(duration * sample_rate), samplerate=sample_rate, channels=1)
    sd.wait()

    return np.linalg.norm(audio)

# 🔹 Quantum inference
def quantum_inference(value, param):
    qc = create_vqc()
    bound_qc = qc.assign_parameters({theta: value * param})

    job = simulator.run(bound_qc, shots=256)
    result = job.result()
    counts = result.get_counts()

    return counts.get('00', 0) / 256

# 🔹 Training
def train_model():
    print("🧠 Training Quantum Model...\n")

    param = 1.0

    for epoch in range(5):
        sample = np.random.uniform(0, 1)

        output = quantum_inference(sample, param)
        target = sample

        loss = (output - target) ** 2
        grad = (output - target)

        param -= 0.2 * grad

        print(f"Epoch {epoch+1} | Loss: {loss:.4f} | Param: {param:.3f}")

    print("\n✅ Training Complete\n")
    return param

# 🔹 Volume bar
def draw_bar(value, length=30):
    filled = int(value * length)
    return "█" * filled + "░" * (length - filled)

# 🔹 Hysteresis classification (REALISTIC)
def classify(norm_signal):
    global current_state

    if current_state == "✅ Clean Signal":
        if norm_signal > 0.65:
            current_state = "⚠️ High Noise"
        elif norm_signal > 0.35:
            current_state = "🔄 Moderate Signal"

    elif current_state == "🔄 Moderate Signal":
        if norm_signal > 0.75:
            current_state = "⚠️ High Noise"
        elif norm_signal < 0.25:
            current_state = "✅ Clean Signal"

    elif current_state == "⚠️ High Noise":
        if norm_signal < 0.55:
            current_state = "🔄 Moderate Signal"

    return current_state

# 🔹 MAIN
if __name__ == "__main__":

    trained_param = train_model()

    print("\n Quantum Noise Detection Started\n")
    print("System Active\n")

    history = []

    while True:
        raw_signal = get_live_signal()
        norm_signal = normalize(raw_signal)

        dynamic_param = trained_param + np.random.uniform(-0.1, 0.1)
        quantum_output = quantum_inference(norm_signal, dynamic_param)

        # smoothing quantum (display only)
        history.append(quantum_output)
        if len(history) > 5:
            history.pop(0)

        smoothed = sum(history) / len(history)

        # 🔥 stable classification
        status = classify(norm_signal)

        # UI bar
        bar = draw_bar(norm_signal)

        print(
            f"[{bar}] {norm_signal:.2f} | Quantum: {quantum_output:.2f} | "
            f"Smooth: {smoothed:.2f} | Status: {status}"
        )

        time.sleep(1)
        