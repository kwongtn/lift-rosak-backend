#!groovy

pipeline {
    agent none
    stages {
        stage('Docker Build') {
            agent any
            steps {
                sh 'docker build --tag=kwongtn/rosak_backend:latest --tag=kwongtn/rosak_backend:$(date +%Y%m%d-%H%M) .'
            }
        }
        stage('Docker Push') {
            agent any
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
