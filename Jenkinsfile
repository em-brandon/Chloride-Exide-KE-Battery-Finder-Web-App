pipeline {
    agent any
    environment {
        // Set up Python and Node.js versions as needed
        PYTHON_VERSION = '3.10'
        NODE_VERSION = '20'
        // Matches docker-compose.yml's local Postgres — the pytest integration
        // suite (backend/tests/) uses this as its real test database.
        DATABASE_URL = 'postgresql://batteryfinder:batteryfinder@127.0.0.1:5434/batteryfinderdev'
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
                sh 'pip install -r backend/requirements-dev.txt'   // dev set: runtime + pipeline + pytest
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
        stage('Test Frontend (vitest)') {
            steps {
                sh 'export PATH="$HOME/.bun/bin:$PATH" && cd frontend && bun run test:ci'
            }
        }
        stage('Start test database') {
            steps {
                // Requires Docker on the Jenkins agent. Brings up the same
                // Postgres 15 container docker-compose.yml defines for local
                // dev, migrated to head before the integration suite runs.
                sh 'docker compose up -d'
                sh 'cd backend && alembic upgrade head'
            }
        }
        stage('Test Python (pytest)') {
            steps {
                sh 'cd backend && pytest --junitxml=test-results.xml'
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
            junit testResults: '**/test-results.xml', allowEmptyResults: true
            sh 'docker compose down || true'
        }
        failure {
            mail to: 'your-team@example.com', subject: 'Build Failed', body: 'Check Jenkins for details.'
        }
    }
}
