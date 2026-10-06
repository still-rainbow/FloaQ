package com.floaq;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.ConfigurationPropertiesScan;

@SpringBootApplication
// @ConfigurationProperties 레코드를 빈으로 올린다 (OceanApiProperties 등)
@ConfigurationPropertiesScan
public class FloaqApplication {

    public static void main(String[] args) {
        SpringApplication.run(FloaqApplication.class, args);
    }
}
