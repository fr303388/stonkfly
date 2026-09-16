// fly-brain style 3D neuron visualization
// Uses DataTexture + custom GLSL shaders for efficient 166k neuron rendering
// Inspired by https://github.com/Lulzx/fly-brain

class FlyBrain3D {
  constructor(canvas) {
    this.canvas = canvas;
    this.neurons = [];
    this.connections = [];
    this.activity = new Float32Array(0);
    this.colors = new Float32Array(0);
    this.N = 0;
    
    // Brain region colors (fly-brain inspired palette)
    this.regionColors = {
      'retina': [0.35, 0.78, 0.98],      // light blue - sensory
      'lamina': [0.47, 0.71, 0.90],      // blue
      'medulla': [0.18, 0.70, 0.79],     // teal
      'lobula': [0.50, 0.85, 0.75],      // mint
      'lobula_plate': [0.50, 0.85, 0.75],
      'antennal_lobe': [0.23, 0.63, 0.85],
      'mushroom_body': [0.75, 0.52, 0.99], // purple - learning/memory
      'kc': [0.75, 0.52, 0.99],           // Kenyon cells
      'mbon': [0.95, 0.45, 0.71],         // pink - output neurons
      'central_complex': [0.98, 0.71, 0.36], // orange
      'fan_shaped_body': [0.98, 0.71, 0.36],
      'ellipsoid_body': [0.98, 0.71, 0.36],
      'protocerebral_bridge': [0.98, 0.71, 0.36],
      'noduli': [0.98, 0.71, 0.36],
      'lateral_accessory_lobe': [0.98, 0.71, 0.36],
      'dorsal_neuropil': [0.90, 0.62, 0.24],
      'ventral_neuropil': [0.98, 0.80, 0.40],
      'deutocerebrum': [0.95, 0.55, 0.20],
      'tritocerebrum': [0.95, 0.55, 0.20],
      'subesophageal': [0.95, 0.55, 0.20],
      'vnc': [0.98, 0.80, 0.40],          // yellow - ventral nerve cord
      'motor': [0.98, 0.44, 0.52],        // red - motor
      'sensory': [0.35, 0.78, 0.98],      // blue - sensory
      'interneuron': [0.42, 0.87, 0.50],  // green
      'modulatory': [0.95, 0.45, 0.71],   // pink
      'default': [0.42, 0.45, 0.50]       // gray
    };
    
    this.init();
  }
  
  init() {
    const w = this.canvas.clientWidth || 400;
    const h = this.canvas.clientHeight || 300;
    
    this.renderer = new THREE.WebGLRenderer({ 
      canvas: this.canvas, 
      antialias: true, 
      alpha: true,
      powerPreference: 'high-performance'
    });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.setSize(w, h);
    
    this.scene = new THREE.Scene();
    this.scene.fog = new THREE.FogExp2(0x000000, 0.008);
    
    this.camera = new THREE.PerspectiveCamera(50, w / h, 0.1, 2000);
    this.camera.position.set(0, 0, 120);
    
    this.controls = new THREE.OrbitControls(this.camera, this.canvas);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.08;
    this.controls.autoRotate = true;
    this.controls.autoRotateSpeed = 0.3;
    
    // Post-processing - bloom
    this.composer = new THREE.EffectComposer(this.renderer);
    this.renderPass = new THREE.RenderPass(this.scene, this.camera);
    this.composer.addPass(this.renderPass);
    
    this.bloomPass = new THREE.UnrealBloomPass(
      new THREE.Vector2(w, h),
      1.2,  // strength
      0.6,  // radius
      0.1   // threshold
    );
    this.composer.addPass(this.bloomPass);
    
    // Lights
    this.scene.add(new THREE.AmbientLight(0xffffff, 0.5));
    const dirLight = new THREE.DirectionalLight(0xffffff, 0.8);
    dirLight.position.set(50, 100, 50);
    this.scene.add(dirLight);
    
    this.impulseParticles = null;
    this.skeletonLines = null;
    this.points = null;
    this.clock = new THREE.Clock();
    
    window.addEventListener('resize', () => this.onResize());
  }
  
  // Generate anatomically-inspired neuron positions
  generateNeurons(n_neurons = 166700) {
    this.N = n_neurons;
    const positions = new Float32Array(n_neurons * 3);
    const colors = new Float32Array(n_neurons * 3);
    const regions = new Array(n_neurons);
    
    // Brain region distribution (approximate Drosophila CNS)
    const regionDist = [
      { name: 'sensory', count: Math.floor(n_neurons * 0.25), center: [0, 20, 0], spread: [25, 15, 20] },
      { name: 'mushroom_body', count: Math.floor(n_neurons * 0.20), center: [0, 5, 10], spread: [20, 12, 15] },
      { name: 'central_complex', count: Math.floor(n_neurons * 0.08), center: [0, 0, 0], spread: [12, 8, 10] },
      { name: 'interneuron', count: Math.floor(n_neurons * 0.25), center: [0, -5, -5], spread: [30, 20, 25] },
      { name: 'motor', count: Math.floor(n_neurons * 0.12), center: [0, -25, 0], spread: [20, 15, 15] },
      { name: 'modulatory', count: Math.floor(n_neurons * 0.05), center: [0, 10, -10], spread: [15, 10, 12] },
      { name: 'vnc', count: n_neurons - Math.floor(n_neurons * 0.95), center: [0, -50, 0], spread: [15, 30, 12] }
    ];
    
    let idx = 0;
    for (const region of regionDist) {
      const color = this.regionColors[region.name] || this.regionColors.default;
      for (let i = 0; i < region.count && idx < n_neurons; i++) {
        // Gaussian-like distribution
        const r = () => (Math.random() + Math.random() + Math.random() - 1.5) * 0.67;
        positions[idx * 3] = region.center[0] + r() * region.spread[0];
        positions[idx * 3 + 1] = region.center[1] + r() * region.spread[1];
        positions[idx * 3 + 2] = region.center[2] + r() * region.spread[2];
        
        colors[idx * 3] = color[0];
        colors[idx * 3 + 1] = color[1];
        colors[idx * 3 + 2] = color[2];
        
        regions[idx] = region.name;
        idx++;
      }
    }
    
    this.positions = positions;
    this.colors = colors;
    this.regions = regions;
    this.activity = new Float32Array(n_neurons);
    
    this.buildPoints();
    this.buildConnections();
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
    
    // Custom shader material for fly-brain style rendering
    const material = new THREE.ShaderMaterial({
      uniforms: {
        time: { value: 0 },
        pixelRatio: { value: this.renderer.getPixelRatio() }
      },
      vertexShader: `
        attribute vec3 color;
        varying vec3 vColor;
        varying float vDist;
        uniform float pixelRatio;
        void main() {
          vColor = color;
          vec4 mvPosition = modelViewMatrix * vec4(position, 1.0);
          vDist = -mvPosition.z;
          gl_Position = projectionMatrix * mvPosition;
          gl_PointSize = (2.0 + 1.5 * pixelRatio) * (300.0 / vDist);
        }
      `,
      fragmentShader: `
        varying vec3 vColor;
        varying float vDist;
        uniform float time;
        void main() {
          float d = length(gl_PointCoord - vec2(0.5));
          if (d > 0.5) discard;
          float glow = 1.0 - smoothstep(0.0, 0.5, d);
          vec3 col = vColor * (0.6 + 0.8 * glow);
          float alpha = 0.15 + 0.6 * glow;
          gl_FragColor = vec4(col, alpha);
        }
      `,
      transparent: true,
      blending: THREE.AdditiveBlending,
      depthWrite: false
    });
    
    this.points = new THREE.Points(geometry, material);
    this.scene.add(this.points);
  }
  
  buildConnections() {
    // Generate sparse connections (sample ~50k connections for visualization)
    const nConn = 50000;
    const linePositions = new Float32Array(nConn * 6);
    const lineColors = new Float32Array(nConn * 6);
    
    for (let i = 0; i < nConn; i++) {
      const a = Math.floor(Math.random() * this.N);
      const b = Math.floor(Math.random() * this.N);
      
      linePositions[i * 6] = this.positions[a * 3];
      linePositions[i * 6 + 1] = this.positions[a * 3 + 1];
      linePositions[i * 6 + 2] = this.positions[a * 3 + 2];
      linePositions[i * 6 + 3] = this.positions[b * 3];
      linePositions[i * 6 + 4] = this.positions[b * 3 + 1];
      linePositions[i * 6 + 5] = this.positions[b * 3 + 2];
      
      const ca = this.colors[a * 3];
      const cb = this.colors[b * 3];
      lineColors[i * 6] = ca * 0.3;
      lineColors[i * 6 + 1] = this.colors[a * 3 + 1] * 0.3;
      lineColors[i * 6 + 2] = this.colors[a * 3 + 2] * 0.3;
      lineColors[i * 6 + 3] = cb * 0.3;
      lineColors[i * 6 + 4] = this.colors[b * 3 + 1] * 0.3;
      lineColors[i * 6 + 5] = this.colors[b * 3 + 2] * 0.3;
    }
    
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(linePositions, 3));
    geometry.setAttribute('color', new THREE.BufferAttribute(lineColors, 3));
    
    const material = new THREE.LineBasicMaterial({
      vertexColors: true,
      transparent: true,
      opacity: 0.08,
      blending: THREE.AdditiveBlending,
      depthWrite: false
    });
    
    if (this.connectionLines) {
      this.scene.remove(this.connectionLines);
    }
    this.connectionLines = new THREE.LineSegments(geometry, material);
    this.scene.add(this.connectionLines);
  }
  
  buildSkeletons() {
    // Add neuron skeleton-like fibers (curved lines through brain regions)
    const nFibers = 200;
    const pointsPerFiber = 8;
    const linePositions = [];
    const lineColors = [];
    
    const fiberColors = [
      [0.35, 0.78, 0.98], // sensory - blue
      [0.75, 0.52, 0.99], // mushroom body - purple
      [0.98, 0.71, 0.36], // central complex - orange
      [0.42, 0.87, 0.50], // interneuron - green
      [0.98, 0.44, 0.52]  // motor - red
    ];
    
    for (let f = 0; f < nFibers; f++) {
      const color = fiberColors[Math.floor(Math.random() * fiberColors.length)];
      const startRegion = Math.floor(Math.random() * 7);
      const endRegion = Math.floor(Math.random() * 7);
      
      const centers = [
        [0, 20, 0], [0, 5, 10], [0, 0, 0], [0, -5, -5],
        [0, -25, 0], [0, 10, -10], [0, -50, 0]
      ];
      
      const start = centers[startRegion];
      const end = centers[endRegion];
      
      let prevPoint = null;
      for (let p = 0; p <= pointsPerFiber; p++) {
        const t = p / pointsPerFiber;
        const x = start[0] + (end[0] - start[0]) * t + (Math.random() - 0.5) * 15;
        const y = start[1] + (end[1] - start[1]) * t + (Math.random() - 0.5) * 10;
        const z = start[2] + (end[2] - start[2]) * t + (Math.random() - 0.5) * 12;
        
        if (prevPoint) {
          linePositions.push(prevPoint[0], prevPoint[1], prevPoint[2], x, y, z);
          lineColors.push(color[0] * 0.4, color[1] * 0.4, color[2] * 0.4,
                          color[0] * 0.4, color[1] * 0.4, color[2] * 0.4);
        }
        prevPoint = [x, y, z];
      }
    }
    
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(linePositions, 3));
    geometry.setAttribute('color', new THREE.Float32BufferAttribute(lineColors, 3));
    
    const material = new THREE.LineBasicMaterial({
      vertexColors: true,
      transparent: true,
      opacity: 0.15,
      blending: THREE.AdditiveBlending,
      depthWrite: false
    });
    
    if (this.skeletonLines) {
      this.scene.remove(this.skeletonLines);
    }
    this.skeletonLines = new THREE.LineSegments(geometry, material);
    this.scene.add(this.skeletonLines);
  }
  
  updateActivity(spikeIndices, spikeRates) {
    // Decay existing activity
    for (let i = 0; i < this.N; i++) {
      this.activity[i] *= 0.92;
    }
    
    // Add new spikes
    if (spikeIndices && spikeRates) {
      for (let i = 0; i < spikeIndices.length; i++) {
        const idx = spikeIndices[i];
        if (idx < this.N) {
          this.activity[idx] = Math.min(1.0, this.activity[idx] + spikeRates[i] * 0.1);
        }
      }
    }
    
    // Update point colors based on activity
    if (this.points) {
      const colorAttr = this.points.geometry.getAttribute('color');
      for (let i = 0; i < this.N; i++) {
        const act = this.activity[i];
        const baseR = this.colors[i * 3];
        const baseG = this.colors[i * 3 + 1];
        const baseB = this.colors[i * 3 + 2];
        
        // Hot color when active (white-yellow)
        const hot = act;
        colorAttr.array[i * 3] = baseR + (1.0 - baseR) * hot;
        colorAttr.array[i * 3 + 1] = baseG + (0.85 - baseG) * hot;
        colorAttr.array[i * 3 + 2] = baseB + (0.3 - baseB) * hot;
      }
      colorAttr.needsUpdate = true;
    }
    
    // Update impulse particles
    this.updateImpulses(spikeIndices);
  }
  
  updateImpulses(spikeIndices) {
    if (!spikeIndices || spikeIndices.length === 0) return;
    
    const nImpulses = Math.min(spikeIndices.length, 200);
    const impPos = new Float32Array(nImpulses * 3);
    const impCol = new Float32Array(nImpulses * 3);
    
    for (let i = 0; i < nImpulses; i++) {
      const idx = spikeIndices[i % spikeIndices.length];
      if (idx < this.N) {
        impPos[i * 3] = this.positions[idx * 3];
        impPos[i * 3 + 1] = this.positions[idx * 3 + 1];
        impPos[i * 3 + 2] = this.positions[idx * 3 + 2];
        
        impCol[i * 3] = 1.0;
        impCol[i * 3 + 1] = 0.9;
        impCol[i * 3 + 2] = 0.4;
      }
    }
    
    if (this.impulseParticles) {
      this.scene.remove(this.impulseParticles);
      this.impulseParticles.geometry.dispose();
      this.impulseParticles.material.dispose();
    }
    
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(impPos, 3));
    geometry.setAttribute('color', new THREE.BufferAttribute(impCol, 3));
    
    const material = new THREE.PointsMaterial({
      size: 3,
      vertexColors: true,
      transparent: true,
      opacity: 0.9,
      blending: THREE.AdditiveBlending,
      depthWrite: false
    });
    
    this.impulseParticles = new THREE.Points(geometry, material);
    this.scene.add(this.impulseParticles);
    
    // Fade out impulses
    setTimeout(() => {
      if (this.impulseParticles) {
        this.impulseParticles.material.opacity = 0;
      }
    }, 500);
  }
  
  setKeyCells(keyCells) {
    // Highlight key cells (KC, MBON, etc.) with larger sprites
    if (!keyCells) return;
    
    // Remove old labels
    if (this.keyCellSprites) {
      this.keyCellSprites.forEach(s => this.scene.remove(s));
    }
    this.keyCellSprites = [];
    
    const labels = Object.entries(keyCells);
    for (const [name, data] of labels) {
      if (!data || !data.position) continue;
      const sprite = this.createLabelSprite(name, data.position);
      this.scene.add(sprite);
      this.keyCellSprites.push(sprite);
    }
  }
  
  createLabelSprite(text, position) {
    const canvas = document.createElement('canvas');
    canvas.width = 256;
    canvas.height = 64;
    const ctx = canvas.getContext('2d');
    ctx.font = 'bold 20px monospace';
    ctx.fillStyle = '#00ffff';
    ctx.textAlign = 'center';
    ctx.fillText(text, 128, 40);
    
    const texture = new THREE.CanvasTexture(canvas);
    const material = new THREE.SpriteMaterial({
      map: texture,
      transparent: true,
      depthTest: false
    });
    const sprite = new THREE.Sprite(material);
    sprite.position.set(position[0], position[1] + 5, position[2]);
    sprite.scale.set(15, 4, 1);
    return sprite;
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
    
    const delta = this.clock.getDelta();
    const time = this.clock.getElapsedTime();
    
    if (this.points && this.points.material.uniforms) {
      this.points.material.uniforms.time.value = time;
    }
    
    // Subtle pulsing of connection lines
    if (this.connectionLines) {
      this.connectionLines.material.opacity = 0.06 + 0.03 * Math.sin(time * 0.5);
    }
    
    this.controls.update();
    this.composer.render();
  }
  
  start() {
    if (!this.N) {
      this.generateNeurons();
    }
    this.animate();
  }
  
  setAutoRotate(enabled) {
    this.controls.autoRotate = enabled;
  }
  
  setView(mode) {
    // mode: 'front', 'side', 'top', 'perspective'
    switch(mode) {
      case 'front':
        this.camera.position.set(0, 0, 120);
        break;
      case 'side':
        this.camera.position.set(120, 0, 0);
        break;
      case 'top':
        this.camera.position.set(0, 120, 0.1);
        break;
      default:
        this.camera.position.set(60, 40, 80);
    }
    this.controls.update();
  }
}
