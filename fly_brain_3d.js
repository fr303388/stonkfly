// fly-brain style 3D neuron visualization v3
// Small points, low opacity, only active neurons glow - like real fly-brain

class FlyBrain3D {
  constructor(canvas) {
    this.canvas = canvas;
    this.N = 0;
    this.activity = null;
    this.init();
  }

  init() {
    const w = this.canvas.clientWidth || 400;
    const h = this.canvas.clientHeight || 300;

    this.renderer = new THREE.WebGLRenderer({
      canvas: this.canvas,
      antialias: false,
      alpha: false,
      powerPreference: 'high-performance'
    });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.setSize(w, h);
    this.renderer.setClearColor(0x000000, 1);

    this.scene = new THREE.Scene();

    this.camera = new THREE.PerspectiveCamera(50, w / h, 0.1, 500);
    this.camera.position.set(0, 5, 70);

    this.controls = new THREE.OrbitControls(this.camera, this.canvas);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.05;
    this.controls.autoRotate = true;
    this.controls.autoRotateSpeed = 0.3;

    // Very subtle bloom
    this.composer = new THREE.EffectComposer(this.renderer);
    this.composer.addPass(new THREE.RenderPass(this.scene, this.camera));
    this.bloomPass = new THREE.UnrealBloomPass(
      new THREE.Vector2(w, h),
      0.25, 0.2, 0.5
    );
    this.composer.addPass(this.bloomPass);

    this.points = null;
    this.skeletonLines = null;
    this.impulseParticles = null;
    this.clock = new THREE.Clock();
    this.time = 0;

    window.addEventListener('resize', () => this.onResize());
  }

  generateNeurons(n_neurons = 166700) {
    this.N = n_neurons;
    this.activity = new Float32Array(n_neurons);

    // Drosophila CNS brain regions - anatomically separated
    // Colors: desaturated, only glow when active
    const REGIONS = [
      {
        name: '視覺', center: [0, 22, 8], spread: [14, 8, 10],
        color: [0.15, 0.45, 0.65], count: Math.floor(n_neurons * 0.20)
      },
      {
        name: '蘑菇體L', center: [-12, 6, 6], spread: [7, 6, 8],
        color: [0.35, 0.20, 0.50], count: Math.floor(n_neurons * 0.15)
      },
      {
        name: '蘑菇體R', center: [12, 6, 6], spread: [7, 6, 8],
        color: [0.40, 0.22, 0.45], count: Math.floor(n_neurons * 0.12)
      },
      {
        name: '中央複合體', center: [0, 0, 0], spread: [6, 4, 6],
        color: [0.15, 0.40, 0.35], count: Math.floor(n_neurons * 0.07)
      },
      {
        name: '聯合', center: [0, -4, -6], spread: [16, 10, 14],
        color: [0.20, 0.25, 0.45], count: Math.floor(n_neurons * 0.22)
      },
      {
        name: '運動', center: [0, -22, 0], spread: [10, 7, 9],
        color: [0.40, 0.20, 0.30], count: Math.floor(n_neurons * 0.10)
      },
      {
        name: '調節', center: [0, 10, -8], spread: [7, 5, 6],
        color: [0.35, 0.30, 0.15], count: Math.floor(n_neurons * 0.06)
      },
      {
        name: 'VNC', center: [0, -42, 0], spread: [6, 16, 6],
        color: [0.18, 0.28, 0.38], count: n_neurons - Math.floor(n_neurons * 0.92)
      }
    ];

    const positions = new Float32Array(n_neurons * 3);
    const colors = new Float32Array(n_neurons * 3);

    let idx = 0;
    REGIONS.forEach(region => {
      for (let i = 0; i < region.count && idx < n_neurons; i++) {
        const g = () => (Math.random() + Math.random() + Math.random() - 1.5) * 0.67;
        positions[idx * 3] = region.center[0] + g() * region.spread[0];
        positions[idx * 3 + 1] = region.center[1] + g() * region.spread[1];
        positions[idx * 3 + 2] = region.center[2] + g() * region.spread[2];
        colors[idx * 3] = region.color[0];
        colors[idx * 3 + 1] = region.color[1];
        colors[idx * 3 + 2] = region.color[2];
        idx++;
      }
    });

    this.positions = positions;
    this.baseColors = new Float32Array(colors);
    this.colors = colors;
    this.regions = REGIONS;

    this.buildPoints();
    this.buildSkeletons();
  }

  buildPoints() {
    if (this.points) {
      this.scene.remove(this.points);
      this.points.geometry.dispose();
      this.points.material.dispose();
    }

    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(this.positions, 3));
    geometry.setAttribute('color', new THREE.BufferAttribute(this.colors, 3));

    // fly-brain style: tiny points, very low opacity, additive blending
    const material = new THREE.PointsMaterial({
      size: 0.35,
      vertexColors: true,
      transparent: true,
      opacity: 0.12,
      sizeAttenuation: true,
      blending: THREE.AdditiveBlending,
      depthWrite: false
    });

    this.points = new THREE.Points(geometry, material);
    this.scene.add(this.points);
  }

  buildSkeletons() {
    // Thin fiber tracts connecting brain regions
    if (this.skeletonLines) {
      this.scene.remove(this.skeletonLines);
      this.skeletonLines.geometry.dispose();
      this.skeletonLines.material.dispose();
    }

    const tracts = [
      [0, 1], [0, 2], [0, 3], [1, 3], [2, 3], [3, 4],
      [4, 5], [3, 6], [5, 7], [1, 4], [2, 4], [6, 4]
    ];

    const linePos = [];
    const lineCol = [];

    tracts.forEach(([a, b]) => {
      const ca = this.regions[a].center;
      const cb = this.regions[b].center;
      const colA = this.regions[a].color;
      const colB = this.regions[b].color;

      // Curved path with intermediate points
      const steps = 6;
      let prev = null;
      for (let s = 0; s <= steps; s++) {
        const t = s / steps;
        const x = ca[0] + (cb[0] - ca[0]) * t + Math.sin(t * Math.PI) * 3;
        const y = ca[1] + (cb[1] - ca[1]) * t;
        const z = ca[2] + (cb[2] - ca[2]) * t + Math.sin(t * Math.PI) * 2;
        if (prev) {
          linePos.push(prev[0], prev[1], prev[2], x, y, z);
          const mix = t;
          lineCol.push(
            colA[0] * (1-mix) + colB[0] * mix,
            colA[1] * (1-mix) + colB[1] * mix,
            colA[2] * (1-mix) + colB[2] * mix,
            colA[0] * (1-mix) + colB[0] * mix,
            colA[1] * (1-mix) + colB[1] * mix,
            colA[2] * (1-mix) + colB[2] * mix
          );
        }
        prev = [x, y, z];
      }
    });

    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.Float32BufferAttribute(linePos, 3));
    geo.setAttribute('color', new THREE.Float32BufferAttribute(lineCol, 3));

    const mat = new THREE.LineBasicMaterial({
      vertexColors: true,
      transparent: true,
      opacity: 0.08,
      blending: THREE.AdditiveBlending,
      depthWrite: false
    });

    this.skeletonLines = new THREE.LineSegments(geo, mat);
    this.scene.add(this.skeletonLines);
  }

  updateActivity(spikeIndices, spikeRates) {
    // Fast decay
    for (let i = 0; i < this.N; i++) {
      this.activity[i] *= 0.85;
    }

    if (spikeIndices && spikeRates) {
      for (let i = 0; i < spikeIndices.length; i++) {
        const idx = spikeIndices[i];
        if (idx < this.N) {
          this.activity[idx] = Math.min(1.0, this.activity[idx] + spikeRates[i] * 0.2);
        }
      }
    }

    // Update colors - active neurons become bright white-cyan
    if (this.points) {
      const colorAttr = this.points.geometry.getAttribute('color');
      let anyActive = false;
      for (let i = 0; i < this.N; i++) {
        const act = this.activity[i];
        if (act > 0.01) anyActive = true;
        const br = this.baseColors[i * 3];
        const bg = this.baseColors[i * 3 + 1];
        const bb = this.baseColors[i * 3 + 2];
        // Active: brighten toward cyan-white
        colorAttr.array[i * 3] = br + (0.7 - br) * act;
        colorAttr.array[i * 3 + 1] = bg + (0.9 - bg) * act;
        colorAttr.array[i * 3 + 2] = bb + (1.0 - bb) * act;
      }
      colorAttr.needsUpdate = true;

      // Increase point opacity when there's activity
      this.points.material.opacity = anyActive ? 0.25 : 0.12;
    }

    // Show impulse particles for top spikes
    if (spikeIndices && spikeIndices.length > 0) {
      this.showImpulses(spikeIndices.slice(0, 50));
    }
  }

  showImpulses(indices) {
    if (this.impulseParticles) {
      this.scene.remove(this.impulseParticles);
      this.impulseParticles.geometry.dispose();
      this.impulseParticles.material.dispose();
    }

    const n = indices.length;
    const pos = new Float32Array(n * 3);
    for (let i = 0; i < n; i++) {
      const idx = indices[i];
      if (idx < this.N) {
        pos[i * 3] = this.positions[idx * 3];
        pos[i * 3 + 1] = this.positions[idx * 3 + 1];
        pos[i * 3 + 2] = this.positions[idx * 3 + 2];
      }
    }

    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));

    const mat = new THREE.PointsMaterial({
      size: 1.2,
      color: 0x88ffff,
      transparent: true,
      opacity: 0.9,
      blending: THREE.AdditiveBlending,
      depthWrite: false
    });

    this.impulseParticles = new THREE.Points(geo, mat);
    this.scene.add(this.impulseParticles);

    let opacity = 0.9;
    const fade = setInterval(() => {
      opacity -= 0.06;
      if (this.impulseParticles) this.impulseParticles.material.opacity = opacity;
      if (opacity <= 0) {
        clearInterval(fade);
        if (this.impulseParticles) {
          this.scene.remove(this.impulseParticles);
          this.impulseParticles = null;
        }
      }
    }, 40);
  }

  onResize() {
    const w = this.canvas.clientWidth || 400;
    const h = this.canvas.clientHeight || 300;
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(w, h);
    this.composer.setSize(w, h);
  }

  animate() {
    requestAnimationFrame(() => this.animate());
    this.time = this.clock.getElapsedTime();

    // Subtle pulsing of skeleton lines
    if (this.skeletonLines) {
      this.skeletonLines.material.opacity = 0.06 + 0.03 * Math.sin(this.time * 0.5);
    }

    this.controls.update();
    this.composer.render();
  }

  start() {
    if (!this.N) this.generateNeurons();
    this.animate();
  }

  setAutoRotate(v) { this.controls.autoRotate = v; }

  setView(mode) {
    switch(mode) {
      case 'front': this.camera.position.set(0, 0, 70); break;
      case 'side': this.camera.position.set(70, 0, 0); break;
      case 'top': this.camera.position.set(0, 70, 0.1); break;
      default: this.camera.position.set(30, 20, 50);
    }
    this.controls.update();
  }
}
