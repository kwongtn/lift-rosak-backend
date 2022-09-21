#!groovy

pipeline {
    agent {
        docker { image 'docker:latest' }
    }
    stages {
        stage('Docker Build') {
            steps {
                sh 'docker build --tag=kwongtn/rosak_backend:latest --tag=kwongtn/rosak_backend:$(date +%Y%m%d-%H%M) .'
            }
        }
        stage('Docker Push') {
            steps {
                withCredentials(
                    [
                        usernamePassword(
                            credentialsId: 'dockerHub',
                            passwordVariable: 'dockerHubPassword',
                            usernameVariable: 'dockerHubUser'
                            )
                    ]
                ) {
                    sh "docker login -u ${env.dockerHubUser} -p ${env.dockerHubPassword}"
                    sh 'docker push kwongtn/rosak_backend:latest'
                }
            }
        }
    }
}
