### Spring Boot skill
- Constructor injection only (no field @Autowired); components package-by-feature.
- @RestController + @RequestMapping at class level; DTO records, never expose entities.
- Validation via jakarta.validation annotations + @Valid; errors via @ControllerAdvice.
- Use ResponseEntity with explicit status; transactions at service layer.
