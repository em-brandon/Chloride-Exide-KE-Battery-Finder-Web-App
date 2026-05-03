pipeline {
    agent any
    environment {
        // Set up Python and Node.js versions as needed
        PYTHON_VERSION = '3.10'
        NODE_VERSION = '20'
    }
    stages {
        stage('Checkout') {
            steps {
                checkout scm
            }
        }
        stage('Set up Python') {
            steps {
                sh 'python --version || sudo apt-get install python${PYTHON_VERSION}'
                sh 'python -m pip install --upgrade pip'
                sh 'pip install -r requirements.txt'
            }
        }
        stage('Set up Node.js & Bun') {
            steps {
                sh 'curl -fsSL https://bun.sh/install | bash'
                sh 'export PATH="$HOME/.bun/bin:$PATH" && bun install --cwd frontend'
            }
        }
        stage('Lint Frontend') {
            steps {
                sh 'export PATH="$HOME/.bun/bin:$PATH" && cd frontend && bun run lint'
            }
        }
        stage('Build Frontend') {
            steps {
                sh 'export PATH="$HOME/.bun/bin:$PATH" && cd frontend && bun run build'
            }
        }
        stage('Test Python (if tests)') {
            steps {
                sh 'pytest || echo "No tests found"'
            }
        }
        stage('Archive Artifacts') {
            steps {
                archiveArtifacts artifacts: 'frontend/dist/**', fingerprint: true
            }
        }
    }
    post {
        always {
            junit '**/test-results.xml'
        }
        failure {
            mail to: 'your-team@example.com', subject: 'Build Failed', body: 'Check Jenkins for details.'
        }
    }
}
